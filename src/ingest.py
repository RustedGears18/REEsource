import rasterio
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from src.config import FILE_PATHS, DOWNSAMPLE_FACTOR, ACTIVE_DIMENSIONS, logging

def load_and_scale_rasters():
    logging.info("Starting Ingestion & Preprocessing Phase.")
    meta = None
    transform = None
    crs = None

    # Filter the target paths based on the requested dimensions
    target_paths = {k: v for k, v in FILE_PATHS.items() if k in ACTIVE_DIMENSIONS}
    
    raster_data = {}
    
    # Iterate ONLY over the filtered target paths
    for feature, path in target_paths.items():
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
            
            raster_data[feature] = arr[::DOWNSAMPLE_FACTOR, ::DOWNSAMPLE_FACTOR]

    min_height = min(arr.shape[0] for arr in raster_data.values())
    min_width = min(arr.shape[1] for arr in raster_data.values())
    
    new_transform = transform * transform.scale(DOWNSAMPLE_FACTOR, DOWNSAMPLE_FACTOR)
    meta.update({'height': min_height, 'width': min_width, 'transform': new_transform})

    # Calculate survey area guardrails
    total_survey_area = abs((min_width * new_transform[0]) * (min_height * new_transform[4]))
    max_cluster_area = total_survey_area * 0.10

    arrays = {feat: arr[:min_height, :min_width].flatten() for feat, arr in raster_data.items()}
    df = pd.DataFrame(arrays)
    df['pixel_idx'] = df.index
    valid_df = df.dropna().copy()
    
    scaler = StandardScaler()
    
    # Dynamically scale ONLY the active dimensions
    scaled_data = scaler.fit_transform(valid_df[ACTIVE_DIMENSIONS])
    
    return valid_df, scaled_data, meta, crs, new_transform, max_cluster_area