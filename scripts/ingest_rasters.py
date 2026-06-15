import os
import glob
from google.cloud import storage
from dotenv import load_dotenv

# Load GCP credentials from your .env file
load_dotenv()

# --- CONFIGURATION ---
# Replace with your actual GCP Project ID and the name of the bucket you created
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reesource")
BUCKET_NAME = "reesource-earth-mri-rasters" # e.g., 'reesource-rasters-dev'
SOURCE_DIR = os.path.join("data", "raw")

def get_gcs_client():
    """Initializes the GCS client using standard Google credentials."""
    try:
        # It will automatically look for GOOGLE_APPLICATION_CREDENTIALS in your environment
        return storage.Client(project=PROJECT_ID)
    except Exception as e:
        print(f"❌ Authentication Error: {e}")
        print("Ensure GOOGLE_APPLICATION_CREDENTIALS is set in your .env file.")
        return None

def upload_large_file(bucket, local_file_path, destination_blob_name):
    """Uploads a file to the bucket using a chunked size for stability."""
    blob = bucket.blob(destination_blob_name)
    
    # Set chunk size to 5 MB. This is highly recommended for files > 10MB
    blob.chunk_size = 5 * 1024 * 1024 
    
    print(f"Uploading: {os.path.basename(local_file_path)}...")
    
    try:
        blob.upload_from_filename(local_file_path, timeout=300)
        gs_uri = f"gs://{bucket.name}/{destination_blob_name}"
        print(f"✅ Success! Available at: {gs_uri}")
        return gs_uri
    except Exception as e:
        print(f"❌ Failed to upload {local_file_path}. Error: {e}")
        return None

def main():
    client = get_gcs_client()
    if not client:
        return

    # Check if bucket exists, if not, create it (requires appropriate permissions)
    try:
        bucket = client.get_bucket(BUCKET_NAME)
    except Exception:
        print(f"Bucket '{BUCKET_NAME}' not found. Attempting to create it...")
        bucket = client.create_bucket(BUCKET_NAME, location="US")
        print(f"Bucket '{BUCKET_NAME}' created successfully.")

    # Find all .tif files in the target directory
    search_pattern = os.path.join(SOURCE_DIR, "**", "*.tif")
    tif_files = glob.glob(search_pattern, recursive=True)

    if not tif_files:
        print(f"No .tif files found in {SOURCE_DIR}.")
        return

    print(f"Found {len(tif_files)} raster files. Commencing upload...\n" + "="*40)

    uploaded_uris = []

    for file_path in tif_files:
        # Keep the folder structure clean in the bucket (e.g., surveys/cmb_mid_2023_eTh.tif)
        file_name = os.path.basename(file_path)
        destination_name = f"surveys/{file_name}"
        
        uri = upload_large_file(bucket, file_path, destination_name)
        if uri:
            uploaded_uris.append(uri)

    print("\n" + "="*40)
    print(f"Ingestion Complete. {len(uploaded_uris)} out of {len(tif_files)} files uploaded.")
    print("Store these URIs in Firestore to link your dashboard to the payloads.")

if __name__ == "__main__":
    main()