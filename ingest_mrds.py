import os
import re
import pandas as pd
from datetime import datetime
import logging
from google.cloud import firestore
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def size_mapper(code):
    """Maps the USGS single-character prod_size code to readable strings."""
    mapping = {'S': 'Small', 'M': 'Medium', 'L': 'Large', 'N': 'None', 'Y': 'Yes (Unspecified)', 'U': 'Unknown'}
    return mapping.get(str(code).upper().strip(), 'Unquantified')

# Broad keywords and fully spelled-out element names for REE detection
REE_TERMS = [
    'REE', 'REO', 'REY', 'RARE EARTH', 'SCANDIUM', 'YTTRIUM', 
    'LANTHANUM', 'CERIUM', 'PRASEODYMIUM', 'NEODYMIUM', 'PROMETHIUM', 
    'SAMARIUM', 'EUROPIUM', 'GADOLINIUM', 'TERBIUM', 'DYSPROSIUM', 
    'HOLMIUM', 'ERBIUM', 'THULIUM', 'YTTERBIUM', 'LUTETIUM'
]

def check_ree(text_list):
    """Scans combined commodity and ore arrays for REE terminology."""
    text = " ".join([str(t).upper() for t in text_list if pd.notna(t)])
    return any(term in text for term in REE_TERMS)

def generate_feedstock_summary(row):
    """Synthesizes the deposit size, viability, and critical mineral/REE presence into a clean summary."""
    size = size_mapper(row.get('prod_size'))
    status = row.get('dev_stat') if pd.notna(row.get('dev_stat')) else 'Unknown Status'
    
    comms = [row.get('commod1'), row.get('commod2'), row.get('commod3')]
    comms_str = ", ".join([str(c) for c in comms if pd.notna(c)])
    comms_text = comms_str if comms_str else 'Uncharacterized'
    
    ore = row.get('ore')
    ore_str = f" Documented ore mineralogy includes {ore}." if pd.notna(ore) else ""
    
    ree_present = check_ree(comms + [ore])
    ree_text = " Confirmed presence of Rare Earth Elements (REEs)." if ree_present else ""
    
    summary = (
        f"Viability & Status: Classified as a '{status}' with a deposit size estimated as '{size}'. "
        f"Primary/Secondary Commodities: {comms_text}.{ore_str}{ree_text}"
    )
    return summary

def process_and_upsert_mrds(csv_path, collection_name='mrds_feedstock_profiles'):
    try:
        logging.info(f"Loading local MRDS dataset from {csv_path}...")
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = df.columns.str.strip().str.lower()
        
        if df.empty:
            logging.warning("The provided dataset is empty.")
            return

        db = firestore.Client()
        collection_ref = db.collection(collection_name)
        batch = db.batch()
        count = 0

        for _, row in df.iterrows():
            row_dict = {k: (v if not pd.isna(v) else None) for k, v in row.to_dict().items()}
            
            lat = row_dict.get('latitude')
            lon = row_dict.get('longitude')
            
            if lat is None or lon is None:
                continue 

            deposit_name = row_dict.get('site_name', f'Unknown_{count}')
            state = str(row_dict.get('state', '')).strip().upper() if row_dict.get('state') else 'UNKNOWN'
            
            # Deterministic ID based on MRDS dep_id
            dep_id = row_dict.get('dep_id', count)
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(deposit_name)).upper()
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            doc_id = f"MRDS_{dep_id}_{safe_name}"
            
            # Formulate robust commodities array separating on commas and semicolons
            raw_comms = f"{row_dict.get('commod1', '')},{row_dict.get('commod2', '')},{row_dict.get('commod3', '')}"
            primary_commodities = list(set([
                c.strip().upper() for c in re.split(r'[,;]', raw_comms) 
                if c.strip() and c.strip().lower() != 'none'
            ]))

            # Generating the automated viability summary string
            summary = generate_feedstock_summary(row_dict)
            
            # THE NEW MRDS-FOCUSED SCHEMA
            parent_doc = {
                "site_id": doc_id,
                "deposit_name": deposit_name,
                "mrds_id": row_dict.get('mrds_id'),
                "state": state,
                "location": {
                    "latitude": float(lat),
                    "longitude": float(lon)
                },
                "geology": {
                    "deposit_type": row_dict.get('dep_type'),
                    "orebody_formation": row_dict.get('orebody_fm'),
                    "geologic_model": row_dict.get('model')
                },
                "operational_category": row_dict.get('dev_stat'),
                "production_size": size_mapper(row_dict.get('prod_size')),
                "primary_commodities": primary_commodities,
                "ore_minerals": row_dict.get('ore'),
                "gangue_materials": row_dict.get('gangue'),
                "feedstock_summary": summary,
                "source_link": row_dict.get('url'),
                "last_updated": datetime.now().isoformat()
            }
            
            batch.set(collection_ref.document(doc_id), parent_doc, merge=True)
            count += 1
            
            if count % 500 == 0:
                batch.commit()
                logging.info(f"Committed batch segment ({count} documents)...")
                batch = db.batch()

        if count % 500 != 0:
            batch.commit()
            
        logging.info(f"Pipeline Complete. Upserted {count} records into '{collection_name}'.")

    except Exception as e:
        logging.error(f"ETL execution encountered an exception: {e}")

if __name__ == "__main__":
    csv_file = "USGS_MRDS_GRADE_A_US_ONLY_2026.csv"
    if os.path.exists(csv_file):
        process_and_upsert_mrds(csv_file)
    else:
        logging.error(f"Could not find {csv_file} in the local directory. Ensure it is in the same folder.")s