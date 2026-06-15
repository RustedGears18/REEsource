import json
import logging
from google.oauth2 import service_account
from google.cloud import firestore

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def purge_massive_polygons_by_geometry():
    PROJECT_ID = "reesource"
    CREDENTIALS_FILE = "reesource-d2eb4118beff.json"
    COLLECTION_NAME = "ree_targets"
    
    # Let's lower the threshold slightly to catch that specific Gunnison-to-Salida block.
    # A 50km x 50km block is 2500 sq km.
    MAX_ALLOWED_AREA_SQ_KM = 2500.0  
    
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE)
        db = firestore.Client(credentials=credentials, project=PROJECT_ID)
        logging.info("Authenticated successfully with Firestore.")
    except Exception as e:
        logging.error(f"Authentication failed: {e}")
        return

    logging.info(f"Scanning for polygons with a true geometry footprint > {MAX_ALLOWED_AREA_SQ_KM} sq km...")
    docs_to_delete = []
    
    stream = db.collection(COLLECTION_NAME).stream()
    for doc in stream:
        data = doc.to_dict()
        geom_str = data.get('geometry')
        
        if not geom_str:
            continue
            
        try:
            # Parse the GeoJSON string
            geom = json.loads(geom_str)
            
            # Extract coordinates (assuming standard Polygon GeoJSON structure)
            if geom.get('type') == 'Polygon':
                coords = geom['coordinates'][0] # The exterior ring
            elif geom.get('type') == 'MultiPolygon':
                coords = geom['coordinates'][0][0] # First exterior ring of the first polygon
            else:
                continue

            # Find the min/max coordinates
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            
            width_deg = max(lons) - min(lons)
            height_deg = max(lats) - min(lats)
            
            # Approximate conversion to kilometers for Colorado (Latitude ~38-40)
            # 1 degree of Latitude is ~111 km everywhere
            # 1 degree of Longitude at Colorado's latitude is ~85 km
            width_km = width_deg * 85.0
            height_km = height_deg * 111.0
            
            true_area_sq_km = width_km * height_km
            
            if true_area_sq_km > MAX_ALLOWED_AREA_SQ_KM:
                docs_to_delete.append((doc.id, doc.reference, true_area_sq_km))
                
        except Exception as e:
            logging.error(f"Failed to parse geometry for doc {doc.id}: {e}")

    total_found = len(docs_to_delete)
    if total_found == 0:
        logging.info("No massive polygons found. Your collection is clean!")
        return
        
    logging.info(f"Found {total_found} polygons exceeding the size threshold based on true coordinates.")
    
    # Execute Batched Deletions
    batch = db.batch()
    deletions_in_current_batch = 0
    total_deleted = 0
    
    for doc_id, doc_ref, area in docs_to_delete:
        logging.info(f"  -> Queuing {doc_id} for deletion (True Area: {area:.2f} sq km)")
        batch.delete(doc_ref)
        deletions_in_current_batch += 1
        total_deleted += 1
        
        if deletions_in_current_batch == 500:
            logging.info(f"Committing batch of {deletions_in_current_batch} deletions...")
            batch.commit()
            batch = db.batch()
            deletions_in_current_batch = 0
            
    if deletions_in_current_batch > 0:
        logging.info(f"Committing final batch of {deletions_in_current_batch} deletions...")
        batch.commit()
        
    logging.info(f"✅ Successfully purged {total_deleted} massive polygons.")

if __name__ == "__main__":
    confirm = input("Are you sure you want to delete massive polygons based on raw geometry? (y/n): ")
    if confirm.lower() == 'y':
        purge_massive_polygons_by_geometry()
    else:
        print("Operation cancelled.")