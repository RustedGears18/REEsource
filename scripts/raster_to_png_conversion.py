import os
import sys
import tempfile
import rasterio
from rasterio.warp import transform_bounds
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from google.cloud import storage, firestore

# Allow the script to import from the root 'src' directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import PROJECT_ID, logging

# --- GCP Configuration ---
BUCKET_NAME = "reesource-data-raw"
# Adjust this if your files are currently sitting at the root of the bucket
SOURCE_PREFIX = "surveys/raw_tifs/" 
DEST_PREFIX = "surveys/web_pngs/"

def get_gcp_clients():
    """Initializes the GCP clients leveraging the centralized environment (.env)."""
    storage_client = storage.Client(project=PROJECT_ID)
    firestore_client = firestore.Client(project=PROJECT_ID)
    return storage_client, firestore_client

def process_and_upload_raster(doc_id, meta, storage_client, firestore_client, fallback_bounds=None):
    bucket = storage_client.bucket(BUCKET_NAME)
    
    # Construct full bucket paths
    tif_blob_path = f"{SOURCE_PREFIX}{meta['filename']}"
    png_filename = meta["filename"].replace('.tif', '.png')
    png_blob_path = f"{DEST_PREFIX}{png_filename}"
    
    tif_blob = bucket.blob(tif_blob_path)
    png_blob = bucket.blob(png_blob_path)

    with tempfile.TemporaryDirectory() as temp_dir:
        local_tif = os.path.join(temp_dir, meta["filename"])
        local_png = os.path.join(temp_dir, png_filename)
        
        # 1. Download TIF from Bucket
        logging.info(f"Downloading {tif_blob_path} from bucket...")
        tif_blob.download_to_filename(local_tif)
        
        # 2. Convert to PNG & Extract Bounds
        logging.info(f"Processing spatial data for {doc_id}...")
        with rasterio.open(local_tif) as src:
            try:
                left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
                pydeck_bounds = [left, bottom, right, top]
            except Exception as e:
                if fallback_bounds:
                    pydeck_bounds = fallback_bounds
                else:
                    raise ValueError(f"Missing CRS in {meta['filename']} and no fallback bounds.")
            
            # --- Aggressive Mask ---
            band1 = src.read(1)
            nodata = src.nodata

            # Catch official nodata, NaNs, absolute zeros (GDAL padding), and -9999 (USGS filler)
            if nodata is not None:
                mask = (band1 == nodata) | np.isnan(band1) | (band1 == 0.0) | (band1 < -9000)
            else:
                mask = np.isnan(band1) | (band1 == 0.0) | (band1 < -9000)

            data_masked = np.ma.masked_array(band1, mask=mask)
            
            vmin, vmax = data_masked.min(), data_masked.max()
            normalized_data = (data_masked - vmin) / (vmax - vmin)
            
            cmap = plt.get_cmap(meta["cmap"])
            rgba_image = cmap(normalized_data)
            rgba_image[mask, 3] = 0.0 # Make NoData transparent
            
            plt.imsave(local_png, rgba_image)
        
        # 3. Upload PNG back to Bucket
        logging.info(f"Uploading {png_filename} to bucket at {png_blob_path}...")
        png_blob.upload_from_filename(local_png)
        png_blob.make_public() 
        
        # 4. Update Firestore with new bounds and PNG URL
        public_url = png_blob.public_url
        doc_ref = firestore_client.collection('raster_assets').document(doc_id)
        
        payload = {
            "image_url": public_url,
            "bounds": pydeck_bounds, 
            "processing_status": "PNG_Ready"
        }
        doc_ref.set(payload, merge=True)
        logging.info(f"✅ Updated Firestore document: {doc_id}\n")
        
        return pydeck_bounds

if __name__ == "__main__":
    storage_client, firestore_client = get_gcp_clients()
    
    raster_assets = {
        "cmb_mid_2023_u": {"filename": "CO_MID_u.tif", "cmap": "plasma"},
        "cmb_mid_2023_th": {"filename": "CO_MID_th.tif", "cmap": "inferno"},
        "cmb_mid_2023_k": {"filename": "CO_MID_k.tif", "cmap": "viridis"},
        "cmb_mid_2023_rtp": {"filename": "CO_MID_rtp.tif", "cmap": "cividis"}
    }
    
    master_bounds = None
    for doc_id, meta in raster_assets.items():
        bounds = process_and_upload_raster(doc_id, meta, storage_client, firestore_client, master_bounds)
        if master_bounds is None:
            master_bounds = bounds
            
    logging.info("--- PNG Conversion Pipeline Execution Complete ---")