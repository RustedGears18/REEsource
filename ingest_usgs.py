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

# Load environment variables from the local .env file
load_dotenv()

# Configure standard logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_resilient_session():
    """
    Creates a requests Session with exponential backoff to handle 
    federal server connectivity drops or timeouts.
    """
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

def resolve_sciencebase_id_from_catalog(session):
    """
    Step 1: Query Data.gov by title to locate the current, active
    ScienceBase Item ID dynamically.
    """
    search_url = "https://catalog.data.gov/search"
    params = {
        'q': '"Critical mineral deposits of the United States"',
        'per_page': 1
    }
    
    try:
        logging.info("Step 1: Resolving dataset via Data.gov Catalog...")
        response = session.get(search_url, params=params, timeout=15)
        response.raise_for_status()
        
        results = response.json().get('results', [])
        if not results:
            logging.error("No matching dataset found on Data.gov by title.")
            return None, None
            
        dataset = results[0]
        title = dataset.get('title')
        dcat_meta = dataset.get('dcat', {})
        modified_str = dcat_meta.get('modified', '')
        
        landing_page = dcat_meta.get('landingPage', '')
        identifier = dcat_meta.get('identifier', '')
        
        match = re.search(r'([a-f0-9]{24})', str(landing_page) + " " + str(identifier))
        
        if match:
            sb_id = match.group(1)
            logging.info(f"Target Confirmed: {title}")
            logging.info(f"Dynamically resolved active ScienceBase ID: {sb_id}")
            return sb_id, modified_str
        else:
            logging.error("Could not parse a valid 24-char hex ScienceBase ID from Data.gov metadata.")
            return None, None

    except Exception as e:
        logging.error(f"Data.gov catalog resolution failed: {e}")
        return None, None

def get_sciencebase_csv_url(item_id, session):
    """
    Step 2: Hit the specific ScienceBase endpoint to find the direct 
    CSV attachment link.
    """
    sciencebase_url = f"https://www.sciencebase.gov/catalog/item/{item_id}"
    params = {'format': 'json'}
    
    try:
        logging.info(f"Step 2: Querying ScienceBase API for secure download URL...")
        response = session.get(sciencebase_url, params=params, timeout=30)
        response.raise_for_status()
        
        files = response.json().get('files', [])
        for file_obj in files:
            filename = file_obj.get('name', '').lower()
            content_type = file_obj.get('contentType', '').lower()
            
            if filename.endswith('.csv') or content_type == 'text/csv':
                download_url = file_obj.get('url')
                logging.info("Direct CSV asset endpoint located.")
                return download_url
                
        logging.error("ScienceBase record found, but no CSV attachment is present.")
        return None
        
    except Exception as e:
        logging.error(f"ScienceBase lookup failed: {e}")
        return None

def process_and_upsert_parents(csv_url, metadata_date, session, collection_name='usmin_critical_minerals'):
    """
    Step 3: Stream download the CSV, clean headers, transform 
    to the parent NoSQL schema, and upsert with merge=True.
    """
    try:
        logging.info("Step 3: Downloading raw dataset matrix...")
        response = session.get(csv_url, stream=True, timeout=60)
        response.raise_for_status()
        
        df = pd.read_csv(response.raw, encoding='utf-8-sig')
        df.columns = df.columns.str.strip().str.lower()
        
        # Standardize state column format for nationwide processing
        if 'state' in df.columns:
            df['state'] = df['state'].astype(str).str.strip().str.upper()
            
        if df.empty:
            logging.warning("No tracking records matched after processing.")
            return

        logging.info(f"Found {len(df)} matching parent nodes. Executing Firestore updates...")
        
        db = firestore.Client()
        collection_ref = db.collection(collection_name)
        batch = db.batch()
        count = 0

        for _, row in df.iterrows():
            row_data = {k: (v if not pd.isna(v) else None) for k, v in row.to_dict().items()}
            
            raw_name = str(row_data.get('deposit', f'unknown_{count}'))
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', raw_name).upper()
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            
            doc_id = f"USMIN_{safe_name}"
            
            parent_doc = {
                "site_id": doc_id,
                "deposit_name": row_data.get('deposit'),
                "state": row_data.get('state'),
                "location": {
                    "latitude": float(row_data.get('lat_wgs84', 0.0)) if row_data.get('lat_wgs84') else None,
                    "longitude": float(row_data.get('long_wgs84', 0.0)) if row_data.get('long_wgs84') else None
                },
                "geology": {
                    "mineral_system": row_data.get('minsystem'),
                    "deposit_type": row_data.get('deptype')
                },
                "operational_category": row_data.get('depcat'),
                "primary_commodities": [
                    c.strip() for c in str(row_data.get('critmin', '')).split(',') if c.strip()
                ],
                "source_link": row_data.get('links'),
                "last_updated_usmin": metadata_date or datetime.now().isoformat()
            }
            
            doc_ref = collection_ref.document(doc_id)
            batch.set(doc_ref, parent_doc, merge=True)
            count += 1
            
            if count % 500 == 0:
                batch.commit()
                logging.info(f"Committed batch segment ({count} documents)...")
                batch = db.batch()

        if count % 500 != 0:
            batch.commit()
            
        logging.info(f"Pipeline Refresh Complete. Upserted {count} verified tracking records into {collection_name}.")

    except Exception as e:
        logging.error(f"ETL Execution loop encountered an exception: {e}")

if __name__ == "__main__":
    http_session = get_resilient_session()
    active_id, mod_date = resolve_sciencebase_id_from_catalog(http_session)
    
    if active_id:
        csv_download_url = get_sciencebase_csv_url(active_id, http_session)
        if csv_download_url:
            # Pushes the national dataset to the unified collection
            process_and_upsert_parents(csv_download_url, mod_date, http_session)