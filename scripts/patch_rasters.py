import os
import logging
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.cloud import firestore

# --- Setup Production Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

def insert_raster_assets():
    # 1. Load basic environment variables (Project ID)
    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID", "reesource")

    # 2. Native GCP File Authentication
    try:
        credentials = service_account.Credentials.from_service_account_file("reesource-d2eb4118beff.json")
        db = firestore.Client(credentials=credentials, project=project_id)
        logging.info(f"Authenticated successfully with project ID: {project_id}")
    except Exception as e:
        logging.error(f"Failed to initialize Firestore client via credentials file: {e}")
        return

    # 3. Define target bucket configuration
    BUCKET_NAME = "reesource-raster-assets"  # <-- Verify this matches your target storage bucket name
    collection_ref = db.collection('raster_assets')
    
    # 4. Master Payload Dictionary
    # Contains the Document ID, exact COG filename, and all required metadata
    raster_assets = {
        "cmb_mid_2023_k": {
            "filename": "CO_MID_k.tif",
            "type": "Radiometric",
            "proxy_metric": "K",
            "name": "Potassium (K)"
        },
        "cmb_mid_2023_rtp": {
            "filename": "CO_MID_rtp.tif",
            "type": "Magnetic",
            "proxy_metric": "RTP",
            "name": "Reduced to Pole (Mag)"
        },
        "cmb_mid_2023_eth": {
            "filename": "CO_MID_th.tif",
            "type": "Radiometric",
            "proxy_metric": "eTh",
            "name": "Equivalent Thorium (eTh)"
        },
        "cmb_mid_2023_u": {
            "filename": "CO_MID_u.tif",
            "type": "Radiometric",
            "proxy_metric": "U",
            "name": "Equivalent Uranium (U)"
        }
    }

    logging_count = 0
    logging.info("Beginning fresh Firestore insertions...")

    # 5. Iterate and insert documents
    for doc_id, meta in raster_assets.items():
        storage_uri = f"gs://{BUCKET_NAME}/{meta['filename']}"
        http_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{meta['filename']}"
        
        doc_ref = collection_ref.document(doc_id)
        
        # Build the full NoSQL document payload
        payload = {
            "original_filename": meta["filename"],
            "parent_survey_id": "cmb_mid_2023",
            "processing_status": "COG_Ready",
            "type": meta["type"],
            "proxy_metric": meta["proxy_metric"],
            "name": meta["name"],
            "storage_uri": storage_uri,
            "url": http_url,
            "image_url": http_url
        }
        
        try:
            # .set(merge=True) acts as a safe "Upsert"
            # It creates the document if missing, or overwrites these specific fields if it exists,
            # which safely preserves your spatial 'bounds' if they are still hiding in the DB.
            doc_ref.set(payload, merge=True)
            logging.info(f"[SUCCESS] Inserted document: {doc_id}")
            logging_count += 1
            
        except Exception as e:
            logging.error(f"[ERROR] Could not insert document '{doc_id}': {e}")

    logging.info(f"Insertion complete. Successfully pushed {logging_count} asset records to Firestore.")

if __name__ == '__main__':
    insert_raster_assets()