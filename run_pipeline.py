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
    
    # --- Grid search parameters for 2D auto-tuning ---
    SEARCH_SIZES = range(10, 260, 20) 
    SEARCH_EPSILONS = [0.0, 0.3, 0.5, 0.7, 1.0] 
    DOWNSAMPLE_FACTOR = 2  

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

    # --- Calculate Total Survey Area for 10% Rejection Logic ---
    total_survey_area = abs((min_width * new_transform[0]) * (min_height * new_transform[4]))
    max_cluster_area = total_survey_area * 0.10
    logging.info("Max allowed anomaly area set to 10% of total survey extent.")

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

    # --- 2. Iterative Analytics Engine (2D Auto-Tuning) ---
    logging.info("Starting HDBSCAN 2D Auto-Tuning Phase...")
    
    best_score = -1.0
    best_size = None
    best_epsilon = None
    best_labels = None

    # Nested loop for Cartesian parameter search
    for min_size in SEARCH_SIZES:
        for current_epsilon in SEARCH_EPSILONS:
            logging.info(f"-> Testing HDBSCAN for min_cluster_size={min_size}, epsilon={current_epsilon}...")
            
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_size, 
                min_samples=15, 
                metric='euclidean', 
                core_dist_n_jobs=6,
                cluster_selection_epsilon=current_epsilon
            )
            
            labels = clusterer.fit_predict(scaled_data)
            
            # Evaluate model validity if valid targets are found
            if np.any(labels != -1):
                score = clusterer.relative_validity_
                logging.info(f"   DBCV Score: {score:.3f}")
                
                # Capture the highest scoring model configuration
                if score > best_score:
                    best_score = score
                    best_size = min_size
                    best_epsilon = current_epsilon
                    best_labels = labels
            else:
                logging.info(f"   No target clusters found for size {min_size}, eps {current_epsilon}.")
                
            # Explicit memory management for the nested loop
            del clusterer, labels
            gc.collect()

    if best_labels is None:
        logging.error("Optimization failed to find any valid clusters. Exiting.")
        return

    logging.info(f"Optimization complete. Best configuration: Size {best_size}, Epsilon {best_epsilon} with DBCV score: {best_score:.3f}")

    # --- 3. Vectorization of Optimal Run ---
    logging.info("Vectorizing optimal clusters...")
    valid_df['final_cluster'] = best_labels
    cluster_means = valid_df[valid_df['final_cluster'] != -1].groupby('final_cluster')[features].mean().to_dict('index')
    valid_df.drop(columns=['final_cluster'], inplace=True)
    
    cluster_grid = np.full(df.shape[0], -1, dtype=np.int32)
    cluster_grid[valid_df['pixel_idx'].values] = best_labels
    cluster_grid = cluster_grid.reshape(meta['height'], meta['width'])

    all_polygons = []
    for geom, value in shapes(cluster_grid, transform=new_transform):
        if value != -1: 
            poly_shape = shape(geom)
            
            # Upstream Size Rejection Guardrail
            if poly_shape.area > max_cluster_area:
                continue 
            
            # Calculate Spatial Dimensions
            bounds = poly_shape.bounds
            width_m = bounds[2] - bounds[0]
            height_m = bounds[3] - bounds[1]
            approx_width_km = round(width_m / 1000, 2)
            approx_height_km = round(height_m / 1000, 2)

            all_polygons.append({
                'geometry': poly_shape,
                'cluster_id': int(value),
                'min_cluster_size': best_size,
                'epsilon': best_epsilon, 
                'width_km': approx_width_km,
                'height_km': approx_height_km,
                'mean_U': round(float(cluster_means[value]['U']), 3),
                'mean_Th': round(float(cluster_means[value]['Th']), 3),
                'mean_K': round(float(cluster_means[value]['K']), 3),
                'mean_Mag': round(float(cluster_means[value]['Mag']), 1)
            })

    del cluster_grid, cluster_means
    gc.collect()

    logging.info(f"Total optimal geometries aggregated: {len(all_polygons)}")

    if not all_polygons:
        logging.error("No valid geometries remained after area rejection. Exiting.")
        return

    gdf = gpd.GeoDataFrame(all_polygons, crs=crs)
    logging.info("Applying buffer smoothing to master geometries...")
    gdf['geometry'] = gdf['geometry'].buffer(100, join_style=2).buffer(-100, join_style=2)
    logging.info("Applying Douglas-Peucker simplification (tolerance=50)...")
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=50, preserve_topology=True)
    logging.info("Reprojecting CRS to EPSG:4326 for web compatibility...")
    gdf = gdf.to_crs("EPSG:4326")

    # The Safety Net
    logging.info("Saving local backup to backup_targets.geojson...")
    gdf.to_file("backup_targets.geojson", driver="GeoJSON")

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
        epsilon_val = props['epsilon'] 
        
        doc_ref = db.collection(COLLECTION_NAME).document(f"target_size{min_size}_eps{epsilon_val}_id{cluster_id}")
        
        payload = {
            'cluster_id': cluster_id,
            'min_cluster_size': min_size,
            'epsilon': epsilon_val, 
            'width_km': props['width_km'],
            'height_km': props['height_km'],
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