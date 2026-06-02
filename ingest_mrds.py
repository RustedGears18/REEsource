import os
import re
import pandas as pd
from datetime import datetime
import logging
from google.cloud import firestore
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def size_mapper(code):
    mapping = {'S': 'Small', 'M': 'Medium', 'L': 'Large', 'N': 'None', 'Y': 'Yes (Unspecified)', 'U': 'Unknown'}
    return mapping.get(str(code).upper().strip(), 'Unquantified')

def split_comms(comm_str):
    """Safely splits a mixed-delimiter string into a clean array, ignoring empty values."""
    if pd.isna(comm_str) or not str(comm_str).strip(): 
        return []
    clean_str = re.sub(r'\(\d+\)', '', str(comm_str)) # Remove parenthetical ranking like (1)
    return list(set([c.strip().upper() for c in re.split(r'[,;]', clean_str) if c.strip() and c.strip().lower() != 'none']))

def generate_feedstock_summary(row):
    size = size_mapper(row.get('prod_size'))
    status = row.get('dev_stat') if pd.notna(row.get('dev_stat')) else 'Unknown Status'
    
    comms = [row.get('commod1'), row.get('commod2'), row.get('commod3')]
    comms_str = ", ".join([str(c) for c in comms if pd.notna(c)])
    comms_text = comms_str if comms_str else 'Uncharacterized'
    
    ore = row.get('ore')
    ore_str = f" Documented ore mineralogy includes {ore}." if pd.notna(ore) else ""
    
    return (
        f"Viability & Status: Classified as a '{status}' with a deposit size estimated as '{size}'. "
        f"Target Commodities: {comms_text}.{ore_str}"
    )

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
            
            dep_id = row_dict.get('dep_id', count)
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(deposit_name)).upper()
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            doc_id = f"MRDS_{dep_id}_{safe_name}"
            
            summary = generate_feedstock_summary(row_dict)
            
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
                    "geologic_model": row_dict.get('model'),
                    "host_rock_unit": row_dict.get('hrock_unit'),
                    "host_rock_type": row_dict.get('hrock_type')
                },
                "operational_category": row_dict.get('dev_stat'),
                "production_size": size_mapper(row_dict.get('prod_size')),
                
                # Separated Commodity Arrays
                "primary_commodities": split_comms(row_dict.get('commod1')),
                "secondary_commodities": split_comms(row_dict.get('commod2')),
                "tertiary_commodities": split_comms(row_dict.get('commod3')),
                
                # Material Strings for later REE estimation
                "ore_minerals": row_dict.get('ore'),
                "gangue_materials": row_dict.get('gangue'),
                "other_materials": row_dict.get('other_matl'),
                
                "cm_present": "Yes",
                "ref": row_dict.get('ref'),
                "disc_yr": str(int(row_dict.get('disc_yr'))) if pd.notna(row_dict.get('disc_yr')) else None,
                "yr_fst_prd": str(int(row_dict.get('yr_fst_prd'))) if pd.notna(row_dict.get('yr_fst_prd')) else None,
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(script_dir, "USGS_MRDS_GRADE_A_US_ONLY_2026.csv")
    
    if os.path.exists(csv_file):
        process_and_upsert_mrds(csv_file)
    else:
        logging.error(f"Could not find the dataset. Python is explicitly looking here:\n{csv_file}")