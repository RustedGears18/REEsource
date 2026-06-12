import os
import gc
from dotenv import load_dotenv
import rasterio
from rasterio.features import shapes
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
from sklearn.preprocessing import StandardScaler
import hdbscan
import json
import logging
from google.cloud import firestore

# --- Setup Clean Production Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

def run_pipeline():
    load_dotenv() 
    
    FILE_PATHS = {
        'U': 'data/CO_MID_u.tif',
        'Th': 'data/CO_MID_th.tif',
        'K': 'data/CO_MID_k.tif',
        'Mag': 'data/CO_MID_rtp.tif'
    }
    
    PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reesource")
    COLLECTION_NAME = 'ree_targets'
    
    # Optimally targeted gap-filled cluster sizes
    CLUSTER_SIZES = [250, 200, 175, 150, 125, 100, 75, 50, 25, 10] 
    DOWNSAMPLE_FACTOR = 2  # 

    # --- 1. Ingestion & Preprocessing ---
    logging.info("Starting Ingestion & Preprocessing Phase.")
    raw_arrays = {}
    meta = None

    for feature, path in FILE_PATHS.items():
        logging.info(f"Loading raster: {feature}")
        with rasterio.open(path) as src:
            if meta is None:
                meta = src.meta.copy() 
                transform = src.transform
                crs = src.crs
            
            arr = src.read(1).astype('float32')
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            
            raw_arrays[feature] = arr[::DOWNSAMPLE_FACTOR, ::DOWNSAMPLE_FACTOR]

    min_height = min(arr.shape[0] for arr in raw_arrays.values())
    min_width = min(arr.shape[1] for arr in raw_arrays.values())
    
    new_transform = transform * transform.scale(DOWNSAMPLE_FACTOR, DOWNSAMPLE_FACTOR)
    meta.update({'height': min_height, 'width': min_width, 'transform': new_transform})

    arrays = {}
    for feature, arr in raw_arrays.items():
        cropped_arr = arr[:min_height, :min_width]
        arrays[feature] = cropped_arr.flatten()

    df = pd.DataFrame(arrays)
    df['pixel_idx'] = df.index
    valid_df = df.dropna().copy()
    logging.info(f"Removed voids. Valid pixels ready: {len(valid_df)}")

    # Clear raw arrays from memory early
    del raw_arrays
    gc.collect()

    scaler = StandardScaler()
    features = ['U', 'Th', 'K', 'Mag']
    scaled_data = scaler.fit_transform(valid_df[features])

# --- 2 & 3. Iterative Clustering & Vectorization ---
    logging.info("Starting Iterative Analytics Engine Phase...")
    all_polygons = []

    # You can hardcode epsilon or iterate through a few options
    TARGET_EPSILON = 0.7

    for min_size in CLUSTER_SIZES:
        logging.info(f"-> Executing HDBSCAN for min_cluster_size={min_size}, epsilon={TARGET_EPSILON}")
        
        # Throttled to 6 cores to balance parallel efficiency and RAM overhead
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_size, 
            min_samples=15, 
            metric='euclidean', 
            core_dist_n_jobs=6,
            cluster_selection_epsilon=TARGET_EPSILON # <-- Added Parameter
        )
        
        # Extract labels directly into an isolated array rather than expanding the DataFrame
        labels = clusterer.fit_predict(scaled_data)
        
        # Check if any targets were found (ignoring noise -1)
        if not np.any(labels != -1):
            logging.info(f"   No target clusters found for size {min_size}.")
            del clusterer, labels
            gc.collect()
            continue
            
        # Temporarily bridge labels to calculate unscaled physical means
        valid_df['temp_cluster'] = labels
        cluster_means = valid_df[valid_df['temp_cluster'] != -1].groupby('temp_cluster')[features].mean().to_dict('index')
        valid_df.drop(columns=['temp_cluster'], inplace=True) # Drop immediately
        
        n_clusters = len(cluster_means)
        logging.info(f"   Found {n_clusters} unique target zones.")
        
        # Reconstruct spatial grid mapping using native index array operations
        cluster_grid = np.full(df.shape[0], -1, dtype=np.int32)
        cluster_grid[valid_df['pixel_idx'].values] = labels
        cluster_grid = cluster_grid.reshape(meta['height'], meta['width'])

        # 
        for geom, value in shapes(cluster_grid, transform=new_transform):
            if value != -1: 
                all_polygons.append({
                    'geometry': shape(geom),
                    'cluster_id': int(value),
                    'min_cluster_size': min_size,
                    'epsilon': TARGET_EPSILON, # <-- Track the hyperparameter
                    'mean_U': round(float(cluster_means[value]['U']), 3),
                    'mean_Th': round(float(cluster_means[value]['Th']), 3),
                    'mean_K': round(float(cluster_means[value]['K']), 3),
                    'mean_Mag': round(float(cluster_means[value]['Mag']), 1)
                })

        # --- Explicit Memory Consolidation Protocol ---
        del clusterer, labels, cluster_grid, cluster_means
        gc.collect()

    logging.info(f"Total geometries aggregated across runs: {len(all_polygons)}")

    if not all_polygons:
        logging.error("No geometries generated. Exiting early.")
        return

    gdf = gpd.GeoDataFrame(all_polygons, crs=crs)
    logging.info("Applying buffer smoothing to master geometries...")
    gdf['geometry'] = gdf['geometry'].buffer(100, join_style=2).buffer(-100, join_style=2)
    logging.info("Applying Douglas-Peucker simplification (tolerance=50)...")
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=50, preserve_topology=True)
    logging.info("Reprojecting CRS to EPSG:4326 for web compatibility...")
    gdf = gdf.to_crs("EPSG:4326")

    # --- THE SAFETY NET ---
    logging.info("Saving local backup to backup_targets.geojson...")
    gdf.to_file("backup_targets.geojson", driver="GeoJSON")
    logging.info("Backup secured on local disk.")

    # --- 4. Database Deployment ---
    logging.info("Commencing metadata-enriched push to Firestore...")
    db = firestore.Client(project=PROJECT_ID)

    geojson_data = json.loads(gdf.to_json())
    batch = db.batch()
    count = 0

    for feature in geojson_data['features']:
        props = feature['properties']
        cluster_id = props['cluster_id']
        min_size = props['min_cluster_size']
        epsilon_val = props['epsilon'] # <-- Extract from properties
        
        # Include epsilon in the document ID to prevent overwriting previous tuning runs
        doc_ref = db.collection(COLLECTION_NAME).document(f"target_size{min_size}_eps{epsilon_val}_id{cluster_id}")
        
        payload = {
            'cluster_id': cluster_id,
            'min_cluster_size': min_size,
            'epsilon': epsilon_val, # <-- Add to Firestore payload
            'mean_U_ppm': props['mean_U'],
            'mean_Th_ppm': props['mean_Th'],
            'mean_K_pct': props['mean_K'],
            'mean_Mag_nT': props['mean_Mag'],
            'geometry': json.dumps(feature['geometry']) 
        }
        
        batch.set(doc_ref, payload)
        count += 1
        
        if count % 500 == 0:
            batch.commit()
            batch = db.batch()

    if count % 500 != 0:
        batch.commit()

    logging.info(f"Successfully pushed {count} enriched target zones to Firestore.")

if __name__ == '__main__':
    run_pipeline()