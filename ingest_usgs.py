import os
import re
import requests
import pandas as pd
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from google.cloud import firestore
from dotenv import load_dotenv

load_dotenv()
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

def resolve_sciencebase_id_from_catalog(session, search_query):
    """Dynamically locates the ScienceBase ID via Data.gov using a specific query."""
    search_url = "https://catalog.data.gov/search"
    params = {'q': search_query, 'per_page': 1}
    
    try:
        logging.info(f"Resolving dataset via Data.gov for: {search_query}...")
        response = session.get(search_url, params=params, timeout=15)
        response.raise_for_status()
        
        results = response.json().get('results', [])
        if not results:
            logging.error(f"No matching dataset found for: {search_query}")
            return None, None
            
        dataset = results[0]
        dcat_meta = dataset.get('dcat', {})
        modified_str = dcat_meta.get('modified', '')
        
        landing_page = dcat_meta.get('landingPage', '')
        identifier = dcat_meta.get('identifier', '')
        
        match = re.search(r'([a-f0-9]{24})', str(landing_page) + " " + str(identifier))
        if match:
            sb_id = match.group(1)
            logging.info(f"Target Confirmed. Active ScienceBase ID: {sb_id}")
            return sb_id, modified_str
        else:
            logging.error("Could not parse a valid 24-char hex ScienceBase ID.")
            return None, None

    except Exception as e:
        logging.error(f"Catalog resolution failed: {e}")
        return None, None

def get_sciencebase_csv_url(item_id, session):
    sciencebase_url = f"https://www.sciencebase.gov/catalog/item/{item_id}"
    params = {'format': 'json'}
    
    try:
        response = session.get(sciencebase_url, params=params, timeout=30)
        response.raise_for_status()
        
        files = response.json().get('files', [])
        for file_obj in files:
            filename = file_obj.get('name', '').lower()
            content_type = file_obj.get('contentType', '').lower()
            
            if filename.endswith('.csv') or content_type == 'text/csv':
                return file_obj.get('url')
        return None
    except Exception as e:
        logging.error(f"ScienceBase lookup failed: {e}")
        return None

def standardize_and_upsert(csv_url, metadata_date, session, origin_type, collection_name='usmin_critical_minerals'):
    """Stream downloads, standardizes disparate column names, and upserts to Firestore."""
    try:
        logging.info(f"Downloading raw dataset for {origin_type}...")
        response = session.get(csv_url, stream=True, timeout=60)
        response.raise_for_status()
        
        df = pd.read_csv(response.raw, encoding='utf-8-sig', low_memory=False)
        df.columns = df.columns.str.strip().str.lower()
        
        if df.empty:
            logging.warning(f"No tracking records found for {origin_type}.")
            return

        db = firestore.Client()
        collection_ref = db.collection(collection_name)
        batch = db.batch()
        count = 0

        for _, row in df.iterrows():
            row_dict = {k: (v if not pd.isna(v) else None) for k, v in row.to_dict().items()}
            
            # --- TRANSLATION LAYER: Normalize Column Variations ---
            # Handles 'deposit' (Primary) vs 'site_name' or 'mine_name' (Waste)
            deposit_name = row_dict.get('deposit') or row_dict.get('site_name') or row_dict.get('mine_name') or f"unknown_{count}"
            
            lat = row_dict.get('lat_wgs84') or row_dict.get('latitude')
            lon = row_dict.get('long_wgs84') or row_dict.get('longitude')
            
            state = str(row_dict.get('state', '')).strip().upper() if row_dict.get('state') else None
            
            # Combine commodities lists if they use different headers
            raw_comms = str(row_dict.get('critmin', '')) + "," + str(row_dict.get('commodities', ''))
            primary_commodities = [c.strip() for c in raw_comms.split(',') if c.strip() and c.strip() != 'None']

            if not lat or not lon:
                continue # Skip invalid coordinates

            # Deterministic ID creation
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(deposit_name)).upper()
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            doc_id = f"USMIN_{safe_name}"
            
            parent_doc = {
                "site_id": doc_id,
                "deposit_name": deposit_name,
                "feedstock_origin": origin_type, # The new classification tag
                "state": state,
                "location": {
                    "latitude": float(lat),
                    "longitude": float(lon)
                },
                "geology": {
                    "mineral_system": row_dict.get('minsystem'),
                    "deposit_type": row_dict.get('deptype') or row_dict.get('waste_type')
                },
                "operational_category": row_dict.get('depcat') or row_dict.get('status'),
                "primary_commodities": primary_commodities,
                "source_link": row_dict.get('links') or row_dict.get('url'),
                "last_updated_usmin": metadata_date or datetime.now().isoformat()
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

    except Exception as e:
        logging.error(f"ETL execution encountered an exception: {e}")

if __name__ == "__main__":
    http_session = get_resilient_session()
    
    # 1. Ingest Traditional Primary Ores
    primary_query = '"Critical mineral deposits of the United States"'
    primary_id, primary_date = resolve_sciencebase_id_from_catalog(http_session, primary_query)
    if primary_id:
        url = get_sciencebase_csv_url(primary_id, http_session)
        if url:
            standardize_and_upsert(url, primary_date, http_session, origin_type="Primary Geologic")
            
    # 2. Ingest Secondary Mine Waste / Tailings
    waste_query = '"USMIN Mine Waste"' # Or '"Mine waste and tailings"'
    waste_id, waste_date = resolve_sciencebase_id_from_catalog(http_session, waste_query)
    if waste_id:
        url = get_sciencebase_csv_url(waste_id, http_session)
        if url:
            standardize_and_upsert(url, waste_date, http_session, origin_type="Secondary Mine Waste")