import numpy as np
import geopandas as gpd
from rasterio.features import shapes
from shapely.geometry import shape
from scipy import stats
from src.config import ACTIVE_DIMENSIONS, SURVEY_SOURCE, RUN_TIMESTAMP, logging

def vectorize_clusters(valid_df, best_labels, meta, new_transform, max_cluster_area, crs, best_size, best_epsilon, best_score):
    logging.info("Vectorizing optimal clusters and calculating spatial statistics...")
    
    valid_df['final_cluster'] = best_labels
    cluster_means = valid_df[valid_df['final_cluster'] != -1].groupby('final_cluster')[ACTIVE_DIMENSIONS].mean().to_dict('index')
    cluster_counts = valid_df[valid_df['final_cluster'] != -1].groupby('final_cluster').size()
    
    # 1. Calculate global background statistics for the Z-Test
    # We only test the FIRST dimension in ACTIVE_DIMENSIONS to represent the cluster's primary significance
    primary_dim = ACTIVE_DIMENSIONS[0]
    global_mean = valid_df[primary_dim].mean()
    global_std = valid_df[primary_dim].std()
    
    cluster_grid = np.full(meta['height'] * meta['width'], -1, dtype=np.int32)
    cluster_grid[valid_df['pixel_idx'].values] = best_labels
    cluster_grid = cluster_grid.reshape(meta['height'], meta['width'])

    all_polygons = []
    for geom, value in shapes(cluster_grid, transform=new_transform):
        if value != -1: 
            poly_shape = shape(geom)
            if poly_shape.area > max_cluster_area: continue 
            
            # 2. Calculate the Z-Score and P-Value for this specific polygon
            cluster_size_pixels = cluster_counts[value]
            cluster_mean = cluster_means[value][primary_dim]
            
            # Standard Error of the Mean = global_std / sqrt(n)
            std_error = global_std / np.sqrt(cluster_size_pixels)
            z_score = (cluster_mean - global_mean) / std_error
            
            # Two-tailed P-Value from the Z-score (survival function * 2)
            p_value = stats.norm.sf(abs(z_score)) * 2
            
            bounds = poly_shape.bounds
            
# 1. Define the base spatial metrics everyone gets
            poly_props = {
                'geometry': poly_shape,
                'cluster_id': int(value),
                'survey_source': SURVEY_SOURCE,
                'run_timestamp': RUN_TIMESTAMP,            # <-- NEW INJECTION
                'min_cluster_size': best_size,
                'epsilon': best_epsilon, 
                'dbcv_score': round(float(best_score), 4),
                'z_score': round(float(z_score), 3),       
                'p_value': f"{float(p_value):.2e}",        
                'primary_tested_dim': primary_dim,         
                'width_km': round((bounds[2] - bounds[0]) / 1000, 2),
                'height_km': round((bounds[3] - bounds[1]) / 1000, 2)
            }
            
            if 'U' in ACTIVE_DIMENSIONS: poly_props['mean_U'] = round(float(cluster_means[value]['U']), 3)
            if 'Th' in ACTIVE_DIMENSIONS: poly_props['mean_Th'] = round(float(cluster_means[value]['Th']), 3)
            if 'K' in ACTIVE_DIMENSIONS: poly_props['mean_K'] = round(float(cluster_means[value]['K']), 3)
            if 'Mag' in ACTIVE_DIMENSIONS: poly_props['mean_Mag'] = round(float(cluster_means[value]['Mag']), 1)
                
            all_polygons.append(poly_props)

    if not all_polygons:
        raise ValueError("No valid geometries remained after area rejection.")

    gdf = gpd.GeoDataFrame(all_polygons, crs=crs)
    gdf['geometry'] = gdf['geometry'].buffer(100, join_style=2).buffer(-100, join_style=2).simplify(tolerance=50, preserve_topology=True)
    
    # Reproject to standard Lat/Lon (WGS84) for PyDeck
    gdf = gdf.to_crs("EPSG:4326")
    
    # Now that it is in Lat/Lon, calculate the centroid of each polygon natively
    # (Using the y-axis for Latitude and x-axis for Longitude)
    gdf['center_lat'] = gdf.geometry.centroid.y
    gdf['center_lon'] = gdf.geometry.centroid.x
    
    return gdf