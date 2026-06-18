import json
from google.cloud import firestore
from src.config import PROJECT_ID, COLLECTION_NAME, logging

def push_to_firestore(gdf):
    logging.info("Commencing metadata-enriched push to Firestore...")
    db = firestore.Client(project=PROJECT_ID)
    geojson_data = json.loads(gdf.to_json())
    batch = db.batch()
    count = 0

    for feature in geojson_data['features']:
        props = feature['properties']
        doc_id = f"target_size{props['min_cluster_size']}_eps{props['epsilon']}_id{props['cluster_id']}"
        doc_ref = db.collection(COLLECTION_NAME).document(doc_id)
        
# 1. Define the core payload
        payload = {
            'cluster_id': props['cluster_id'],
            'survey_source': props.get('survey_source', 'Unknown'),  
            'run_timestamp': props.get('run_timestamp'),  # <-- ADDED
            'center_lat': props.get('center_lat'),        # <-- ADDED
            'center_lon': props.get('center_lon'),        # <-- ADDED
            'min_cluster_size': props['min_cluster_size'],
            'epsilon': props['epsilon'], 
            'dbcv_score': props.get('dbcv_score'), 
            'z_score': props.get('z_score'),              
            'p_value': props.get('p_value'),              
            'primary_tested_dim': props.get('primary_tested_dim'),
            'width_km': props['width_km'],
            'height_km': props['height_km'],
            'geometry': json.dumps(feature['geometry']) 
        }
        
        # 2. Dynamically append assays only if they exist in the GeoJSON properties
        if 'mean_U' in props: payload['mean_U_ppm'] = props['mean_U']
        if 'mean_Th' in props: payload['mean_Th_ppm'] = props['mean_Th']
        if 'mean_K' in props: payload['mean_K_pct'] = props['mean_K']
        if 'mean_Mag' in props: payload['mean_Mag_nT'] = props['mean_Mag']
        
        batch.set(doc_ref, payload)
        count += 1
        
        if count % 500 == 0:
            batch.commit()
            batch = db.batch()

    if count % 500 != 0:
        batch.commit()

    logging.info(f"Successfully pushed {count} enriched target zones to Firestore.")