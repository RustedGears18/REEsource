import os
import sys
import tempfile
import rasterio
from google.cloud import storage, firestore

# Allow the script to import from the root 'src' directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import PROJECT_ID, logging

# --- CONFIGURATION ---
BUCKET_NAME = "reesource-data-raw"
DEST_PREFIX = "surveys/cogs/"

def get_clients():
    try:
        db = firestore.Client(project=PROJECT_ID)
        storage_client = storage.Client(project=PROJECT_ID)
        return db, storage_client.bucket(BUCKET_NAME)
    except Exception as e:
        logging.error(f"GCP Auth Error: {e}")
        return None, None

def convert_to_cog(input_path, output_path):
    """Rewrites a standard TIF into a tiled, overview-enabled COG."""
    with rasterio.open(input_path) as src:
        profile = src.profile
        
        profile.update(
            driver="COG",
            compress="deflate",  
            tiled=True,
            blockxsize=256,
            blockysize=256
        )
        
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(src.read())

def main():
    db, bucket = get_clients()
    if not db or not bucket: return

    logging.info("🚀 Initiating REEsource COG Optimization Pipeline...")

    # Query Firestore for assets registered by patch_rasters.py
    raw_assets = db.collection("raster_assets").where("processing_status", "==", "Registered").stream()
    
    processed_count = 0

    for asset in raw_assets:
        doc_id = asset.id
        data = asset.to_dict()
        raw_uri = data.get("raw_storage_uri")
        
        if not raw_uri:
            logging.warning(f"Skipping {doc_id}: No raw_storage_uri found.")
            continue

        blob_path = raw_uri.replace(f"gs://{BUCKET_NAME}/", "")
        filename = blob_path.split("/")[-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            local_raw = os.path.join(temp_dir, f"raw_{filename}")
            local_cog = os.path.join(temp_dir, f"cog_{filename}")

            logging.info(f"📥 Downloading: {filename}")
            
            try:
                # 1. EXTRACT
                blob = bucket.blob(blob_path)
                blob.download_to_filename(local_raw)

                # 2. TRANSFORM
                logging.info("⚙️ Optimizing to COG format...")
                convert_to_cog(local_raw, local_cog)

                # 3. LOAD
                new_blob_path = f"{DEST_PREFIX}{filename}"
                new_blob = bucket.blob(new_blob_path)
                
                new_blob.chunk_size = 5 * 1024 * 1024 
                new_blob.upload_from_filename(local_cog, timeout=300)
                
                new_uri = f"gs://{BUCKET_NAME}/{new_blob_path}"

                # 4. UPDATE
                asset.reference.update({
                    "cog_storage_uri": new_uri,
                    "processing_status": "COG_Optimized"
                })

                logging.info(f"✅ Success! Updated DB: {new_uri}")
                processed_count += 1

            except Exception as e:
                logging.error(f"Pipeline failed for {filename}. Error: {e}")

    logging.info(f"Pipeline Complete. {processed_count} arrays optimized and registered.")

if __name__ == "__main__":
    main()