import os
import sys
from google.cloud import firestore

# Allow the script to import from the root 'src' directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import PROJECT_ID, logging

def insert_raster_assets():
    # 1. Native GCP Authentication via centralized config
    try:
        db = firestore.Client(project=PROJECT_ID)
        logging.info(f"Authenticated successfully with project ID: {PROJECT_ID}")
    except Exception as e:
        logging.error(f"Failed to initialize Firestore client: {e}")
        return

    # 2. Define target bucket configuration
    BUCKET_NAME = "reesource-data-raw"
    TIF_PREFIX = "surveys/raw_tifs"
    collection_ref = db.collection('raster_assets')
    
    # 3. Master Payload Dictionary
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

    # 4. Iterate and insert documents
    for doc_id, meta in raster_assets.items():
        storage_uri = f"gs://{BUCKET_NAME}/{TIF_PREFIX}/{meta['filename']}"
        
        doc_ref = collection_ref.document(doc_id)
        
        # Notice we intentionally omit 'image_url' and 'bounds'.
        # raster_to_png_conversion.py will safely inject those fields later.
        payload = {
            "original_filename": meta["filename"],
            "parent_survey_id": "cmb_mid_2023",
            "processing_status": "Registered", 
            "type": meta["type"],
            "proxy_metric": meta["proxy_metric"],
            "name": meta["name"],
            "raw_storage_uri": storage_uri
        }
        
        try:
            # .set(merge=True) preserves your spatial 'bounds' and PNG urls 
            # if they already exist in the DB.
            doc_ref.set(payload, merge=True)
            logging.info(f"[SUCCESS] Inserted/Updated document: {doc_id}")
            logging_count += 1
            
        except Exception as e:
            logging.error(f"[ERROR] Could not insert document '{doc_id}': {e}")

    logging.info(f"Insertion complete. Successfully pushed {logging_count} asset records to Firestore.")

if __name__ == '__main__':
    insert_raster_assets()