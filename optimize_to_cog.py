import os
import rasterio
from google.cloud import storage, firestore
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BUCKET_NAME = "reesource-earth-mri-rasters"
TEMP_DIR = "temp_processing"

def get_clients():
    try:
        db = firestore.Client()
        storage_client = storage.Client()
        return db, storage_client.bucket(BUCKET_NAME)
    except Exception as e:
        print(f"❌ GCP Auth Error: {e}")
        return None, None

def convert_to_cog(input_path, output_path):
    """Rewrites a standard TIF into a tiled, overview-enabled COG."""
    with rasterio.open(input_path) as src:
        profile = src.profile
        
        # Inject the Cloud Optimized GeoTIFF architecture parameters
        profile.update(
            driver="COG",
            compress="deflate",  # High-efficiency compression
            tiled=True,
            blockxsize=256,
            blockysize=256
        )
        
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(src.read())

def main():
    db, bucket = get_clients()
    if not db or not bucket: return

    # Create a local temp directory for processing
    os.makedirs(TEMP_DIR, exist_ok=True)

    print("🚀 Initiating REEsource COG Optimization Pipeline...\n" + "="*50)

    # Query Firestore for assets that haven't been optimized yet
    raw_assets = db.collection("raster_assets").where("processing_status", "==", "Raw_TIF").stream()
    
    processed_count = 0

    for asset in raw_assets:
        doc_id = asset.id
        data = asset.to_dict()
        raw_uri = data.get("storage_uri")
        
        # Extract the exact path inside the bucket
        blob_path = raw_uri.replace(f"gs://{BUCKET_NAME}/", "")
        filename = blob_path.split("/")[-1]

        local_raw = os.path.join(TEMP_DIR, f"raw_{filename}")
        local_cog = os.path.join(TEMP_DIR, f"cog_{filename}")

        print(f"📥 Downloading: {filename}")
        
        try:
            # 1. EXTRACT: Download from GCS
            blob = bucket.blob(blob_path)
            blob.download_to_filename(local_raw)

            # 2. TRANSFORM: Convert to COG
            print(f"⚙️  Optimizing to COG format...")
            convert_to_cog(local_raw, local_cog)

            # 3. LOAD: Upload the new COG
            new_blob_path = f"cogs/{filename}"
            new_blob = bucket.blob(new_blob_path)
            
            # Use chunked upload for the new file just to be safe
            new_blob.chunk_size = 5 * 1024 * 1024 
            new_blob.upload_from_filename(local_cog, timeout=300)
            
            new_uri = f"gs://{BUCKET_NAME}/{new_blob_path}"

            # 4. UPDATE: Modify the Firestore metadata catalog
            asset.reference.update({
                "storage_uri": new_uri,
                "processing_status": "COG_Ready"
            })

            print(f"✅ Success! Updated DB: {new_uri}\n")
            processed_count += 1

        except Exception as e:
            print(f"❌ Pipeline failed for {filename}. Error: {e}\n")

        finally:
            # Clean up the 50MB temp files so your hard drive doesn't fill up
            if os.path.exists(local_raw): os.remove(local_raw)
            if os.path.exists(local_cog): os.remove(local_cog)

    print("="*50)
    print(f"Pipeline Complete. {processed_count} arrays optimized and registered.")

if __name__ == "__main__":
    main()