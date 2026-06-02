import os
import re
import requests
import pandas as pd
import geopandas as gpd
import tempfile
import zipfile
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from google.cloud import firestore
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure standard logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_resilient_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def get_sciencebase_target(item_id, session):
    """
    Queries ScienceBase and prioritizes downloading a raw CSV.
    If none exists, it hunts for a Shapefile ZIP archive.
    """
    url = f"https://www.sciencebase.gov/catalog/item/{item_id}"
    try:
        resp = session.get(url, params={'format': 'json'}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        
        last_updated = payload.get('provenance', {}).get('lastUpdated', datetime.now().isoformat())
        files = payload.get('files', [])
        
        # 1. Hunt for a valid CSV (aggressively ignoring dictionaries and metadata)
        csv_files = []
        for f in files:
            name = f.get('name', '').lower()
            if name.endswith('.csv') and 'dict' not in name and 'meta' not in name:
                csv_files.append(f)
                
        if csv_files:
            target = max(csv_files, key=lambda x: x.get('size', 0))
            return target.get('url'), last_updated, 'csv'
            
        # 2. Hunt for a Shapefile ZIP
        shp_files = [f for f in files if 'shapefile' in f.get('name', '').lower() and f.get('name', '').lower().endswith('.zip')]
        if shp_files:
            target = max(shp_files, key=lambda x: x.get('size', 0))
            return target.get('url'), last_updated, 'shapefile'
            
        return None, None, None
    except Exception as e:
        logging.error(f"ScienceBase lookup failed for {item_id}: {e}")
        return None, None, None

def check_if_update_needed(db, origin_type, federal_date):
    """Checks the Firestore ETL state to prevent redundant runs."""
    doc_id = re.sub(r'[^a-zA-Z0-9]', '_', origin_type).upper()
    doc_ref = db.collection('etl_pipeline_state').document(doc_id)
    
    state_doc = doc_ref.get()
    if state_doc.exists:
        last_sync = state_doc.to_dict().get('federal_last_modified')
        if last_sync == federal_date:
            logging.info(f"[{origin_type}] Federal source unchanged. Skipping ingestion gracefully.")
            return False, doc_ref
            
    return True, doc_ref

def standardize_and_upsert(file_url, federal_date, file_type, session, origin_type, db, collection_name='usmin_critical_minerals'):
    try:
        logging.info(f"Downloading {file_type} data matrix for {origin_type}...")
        response = session.get(file_url, timeout=60)
        response.raise_for_status()
        
        # --- FORMAT PARSING ROUTINE ---
        if file_type == 'csv':
            from io import BytesIO
            df = pd.read_csv(BytesIO(response.content), encoding='utf-8-sig', low_memory=False)
            
        elif file_type == 'shapefile':
            # Create a robust temporary directory context
            with tempfile.TemporaryDirectory() as tmp_dir:
                zip_path = os.path.join(tmp_dir, "payload.zip")
                
                # Write the bytes to a physical zip file
                with open(zip_path, 'wb') as f:
                    f.write(response.content)
                
                # Extract everything into the temp folder
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                    
                # Hunt through the extracted folder(s) for the actual .shp file
                shp_file_path = None
                for root, _, files in os.walk(tmp_dir):
                    for file in files:
                        if file.endswith('.shp'):
                            shp_file_path = os.path.join(root, file)
                            break
                    if shp_file_path:
                        break
                
                if not shp_file_path:
                    logging.error("Extracted zip successfully, but no .shp file was found inside.")
                    return False
                    
                # GeoPandas can now read a clean, local file path
                gdf = gpd.read_file(shp_file_path)
                df = pd.DataFrame(gdf.drop(columns='geometry'))
        else:
            logging.error(f"Unsupported file type: {file_type}")
            return False

        df.columns = df.columns.str.strip().str.lower()
        
        if df.empty:
            logging.warning(f"No tracking records found for {origin_type}.")
            return False

        collection_ref = db.collection(collection_name)
        batch = db.batch()
        count = 0

        lat_candidates = ['lat_wgs84', 'latitude', 'lat', 'y', 'lat_dd']
        lon_candidates = ['long_wgs84', 'longitude', 'long', 'lon', 'x', 'lon_dd']
        name_candidates = ['deposit', 'site_name', 'mine_name', 'name', 'site_na'] 
        comms_candidates = ['critmin', 'commodities', 'commodity', 'commoditie']

        for _, row in df.iterrows():
            row_dict = {k: (v if not pd.isna(v) else None) for k, v in row.to_dict().items()}
            
            lat = next((row_dict[k] for k in lat_candidates if row_dict.get(k) is not None), None)
            lon = next((row_dict[k] for k in lon_candidates if row_dict.get(k) is not None), None)
            
            if lat is None or lon is None:
                continue 

            deposit_name = next((row_dict[k] for k in name_candidates if row_dict.get(k) is not None), f"unknown_{count}")
            state = str(row_dict.get('state', '')).strip().upper() if row_dict.get('state') else None
            
            raw_comms = ",".join([str(row_dict.get(c, '')) for c in comms_candidates if row_dict.get(c)])
            primary_commodities = list(set([c.strip().upper() for c in raw_comms.split(',') if c.strip() and c.strip().lower() != 'none']))

            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(deposit_name)).upper()
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            doc_id = f"USMIN_{safe_name}"
            
            parent_doc = {
                "site_id": doc_id,
                "deposit_name": deposit_name,
                "feedstock_origin": origin_type,
                "state": state,
                "location": {
                    "latitude": float(lat),
                    "longitude": float(lon)
                },
                "geology": {
                    "mineral_system": row_dict.get('minsystem'),
                    "deposit_type": row_dict.get('deptype') or row_dict.get('waste_type') or row_dict.get('deposit_ty')
                },
                "operational_category": row_dict.get('depcat') or row_dict.get('status') or row_dict.get('operation_'),
                "primary_commodities": primary_commodities,
                "source_link": row_dict.get('links') or row_dict.get('url'),
                "last_updated_usmin": federal_date
            }
            
            batch.set(collection_ref.document(doc_id), parent_doc, merge=True)
            count += 1
            
            if count % 500 == 0:
                batch.commit()
                logging.info(f"Committed batch segment ({count} documents)...")
                batch = db.batch()

        if count % 500 != 0:
            batch.commit()
            
        logging.info(f"Pipeline Complete. Upserted {count} records for {origin_type}.")
        return True # Returns True on a successful execution

    except Exception as e:
        logging.error(f"ETL execution encountered an exception: {e}")
        return False # Returns False so the state doc doesn't get improperly updated

if __name__ == "__main__":
    http_session = get_resilient_session()
    
    targets = [
        {"origin": "Primary Geologic", "id": "6464de5bd34ec179a83d9e6c"},
        {"origin": "Secondary Mine Waste", "id": "686317a5d4be025653d31f09"}
    ]
    
    db_client = firestore.Client()
    
    for target in targets:
        logging.info(f"Checking target: {target['origin']} ({target['id']})")
        
        target_url, fed_date, file_type = get_sciencebase_target(target["id"], http_session)
        
        if not target_url:
            logging.error(f"Could not resolve a valid data matrix for {target['origin']}.")
            continue
            
        needs_update, state_doc_ref = check_if_update_needed(db_client, target["origin"], fed_date)
        
        if needs_update:
            # Only update the state tracker if the ingestion function completely succeeds
            success = standardize_and_upsert(target_url, fed_date, file_type, http_session, target["origin"], db_client)
            
            if success:
                state_doc_ref.set({
                    'federal_last_modified': fed_date, 
                    'last_ingested_local': datetime.now().isoformat()
                }, merge=True)