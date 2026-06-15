import os
import sys
import glob
from google.cloud import storage

# Allow the script to import from the root 'src' directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import PROJECT_ID, logging

# --- UPDATED CONFIGURATION ---
BUCKET_NAME = "reesource-data-raw" 
SOURCE_DIR = os.path.join("data", "raw")

def get_gcs_client():
    """Initializes the GCS client leveraging the centralized environment."""
    try:
        return storage.Client(project=PROJECT_ID)
    except Exception as e:
        logging.error(f"Authentication Error: {e}")
        return None

def upload_large_file(bucket, local_file_path, destination_blob_name):
    """Uploads a file to the bucket using a chunked size for stability."""
    blob = bucket.blob(destination_blob_name)
    blob.chunk_size = 5 * 1024 * 1024  # 5 MB chunks
    
    logging.info(f"Uploading: {os.path.basename(local_file_path)}...")
    
    try:
        blob.upload_from_filename(local_file_path, timeout=300)
        gs_uri = f"gs://{bucket.name}/{destination_blob_name}"
        logging.info(f"✅ Success! Available at: {gs_uri}")
        return gs_uri
    except Exception as e:
        logging.error(f"Failed to upload {local_file_path}. Error: {e}")
        return None

def main():
    logging.info(f"Initiating Bulk Raster Ingestion to {BUCKET_NAME}...")
    client = get_gcs_client()
    if not client:
        return

    try:
        bucket = client.get_bucket(BUCKET_NAME)
    except Exception:
        logging.warning(f"Bucket '{BUCKET_NAME}' not found. Attempting to create it...")
        bucket = client.create_bucket(BUCKET_NAME, location="US")
        logging.info(f"Bucket '{BUCKET_NAME}' created successfully.")

    search_pattern = os.path.join(SOURCE_DIR, "**", "*.tif")
    tif_files = glob.glob(search_pattern, recursive=True)

    if not tif_files:
        logging.warning(f"No .tif files found in {SOURCE_DIR}.")
        return

    logging.info(f"Found {len(tif_files)} raster files. Commencing upload...")

    uploaded_uris = []
    for file_path in tif_files:
        file_name = os.path.basename(file_path)
        # Storing in a logical subdirectory within the raw bucket
        destination_name = f"surveys/raw_tifs/{file_name}"
        
        uri = upload_large_file(bucket, file_path, destination_name)
        if uri:
            uploaded_uris.append(uri)

    logging.info(f"Ingestion Complete. {len(uploaded_uris)} out of {len(tif_files)} files uploaded.")

if __name__ == "__main__":
    main()