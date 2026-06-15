import numpy as np
import geopandas as gpd
from rasterio.features import shapes
from shapely.geometry import shape
from src.config import ACTIVE_DIMENSIONS, logging

# Updated signature to include best_score
def vectorize_clusters(valid_df, best_labels, meta, new_transform, max_cluster_area, crs, best_size, best_epsilon, best_score):
    logging.info("Vectorizing optimal clusters...")
    features = ['U', 'Th', 'K', 'Mag']
    valid_df['final_cluster'] = best_labels
    cluster_means = valid_df[valid_df['final_cluster'] != -1].groupby('final_cluster')[features].mean().to_dict('index')
    
    cluster_grid = np.full(meta['height'] * meta['width'], -1, dtype=np.int32)
    cluster_grid[valid_df['pixel_idx'].values] = best_labels
    cluster_grid = cluster_grid.reshape(meta['height'], meta['width'])

    all_polygons = []
    for geom, value in shapes(cluster_grid, transform=new_transform):
        if value != -1: 
            poly_shape = shape(geom)
            if poly_shape.area > max_cluster_area: continue 
            
            bounds = poly_shape.bounds
            all_polygons.append({
                'geometry': poly_shape,
                'cluster_id': int(value),
                'min_cluster_size': best_size,
                'epsilon': best_epsilon, 
                'dbcv_score': round(float(best_score), 4),
                'width_km': round((bounds[2] - bounds[0]) / 1000, 2),
                'height_km': round((bounds[3] - bounds[1]) / 1000, 2),
                # Gracefully handle missing dimensions
                'mean_U': round(float(cluster_means[value]['U']), 3) if 'U' in ACTIVE_DIMENSIONS else None,
                'mean_Th': round(float(cluster_means[value]['Th']), 3) if 'Th' in ACTIVE_DIMENSIONS else None,
                'mean_K': round(float(cluster_means[value]['K']), 3) if 'K' in ACTIVE_DIMENSIONS else None,
                'mean_Mag': round(float(cluster_means[value]['Mag']), 1) if 'Mag' in ACTIVE_DIMENSIONS else None
            })

    if not all_polygons:
        raise ValueError("No valid geometries remained after area rejection.")

    gdf = gpd.GeoDataFrame(all_polygons, crs=crs)
    
    gdf['geometry'] = gdf['geometry'].buffer(100, join_style=2).buffer(-100, join_style=2)
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=50, preserve_topology=True)
    gdf = gdf.to_crs("EPSG:4326")
    
    gdf.to_file("backup_targets.geojson", driver="GeoJSON")
    return gdf