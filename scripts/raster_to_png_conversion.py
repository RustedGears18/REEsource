import os
import tempfile
import rasterio
from rasterio.warp import transform_bounds
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from google.oauth2 import service_account
from google.cloud import storage, firestore

# --- GCP Configuration ---
PROJECT_ID = "reesource"
BUCKET_NAME = "reesource-data-raw"
CREDENTIALS_FILE = "reesource-d2eb4118beff.json"

def get_gcp_clients():
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE)
    storage_client = storage.Client(credentials=creds, project=PROJECT_ID)
    firestore_client = firestore.Client(credentials=creds, project=PROJECT_ID)
    return storage_client, firestore_client

def process_and_upload_raster(doc_id, meta, storage_client, firestore_client, fallback_bounds=None):
    bucket = storage_client.bucket(BUCKET_NAME)
    tif_blob = bucket.blob(meta["filename"])
    
    png_filename = meta["filename"].replace('.tif', '.png')
    png_blob = bucket.blob(png_filename)

    with tempfile.TemporaryDirectory() as temp_dir:
        local_tif = os.path.join(temp_dir, meta["filename"])
        local_png = os.path.join(temp_dir, png_filename)
        
        # 1. Download TIF from Bucket
        print(f"Downloading {meta['filename']} from bucket...")
        tif_blob.download_to_filename(local_tif)
        
        # 2. Convert to PNG & Extract Bounds
        print(f"Processing spatial data for {doc_id}...")
        with rasterio.open(local_tif) as src:
            try:
                left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
                pydeck_bounds = [left, bottom, right, top]
            except Exception as e:
                if fallback_bounds:
                    pydeck_bounds = fallback_bounds
                else:
                    raise ValueError(f"Missing CRS in {meta['filename']} and no fallback bounds.")
            
            band1 = src.read(1)
            nodata = src.nodata
            mask = (band1 == nodata) | np.isnan(band1) if nodata is not None else np.isnan(band1)
            # --- New Aggressive Mask ---
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
        print(f"Uploading {png_filename} to bucket...")
        png_blob.upload_from_filename(local_png)
        png_blob.make_public() # Ensure Streamlit can read the URL
        
        # 4. Update Firestore with new bounds and PNG URL
        public_url = png_blob.public_url
        doc_ref = firestore_client.collection('raster_assets').document(doc_id)
        
        payload = {
            "image_url": public_url,
            "bounds": pydeck_bounds, # This is what PyDeck was missing!
            "processing_status": "PNG_Ready"
        }
        doc_ref.set(payload, merge=True)
        print(f"✅ Updated Firestore document: {doc_id}\n")
        
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
            
    print("--- Pipeline Execution Complete ---")