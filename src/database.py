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
        
        payload = {
            'cluster_id': props['cluster_id'],
            'min_cluster_size': props['min_cluster_size'],
            'epsilon': props['epsilon'], 
            'dbcv_score': props.get('dbcv_score'), # Injected DBCV Score
            'width_km': props['width_km'],
            'height_km': props['height_km'],
            'mean_U_ppm': props['mean_U'],
            'mean_Th_ppm': props['mean_Th'],
            'mean_K_pct': props['mean_K'],
            'mean_Mag_nT': props['mean_Mag'],
            'geometry': json.dumps(feature['geometry']) 
        }
        
        batch.set(doc_ref, payload)
        count += 1
        
        if count % 500 == 0:
            batch.commit()
            batch = db.batch()

    if count % 500 != 0:
        batch.commit()

    logging.info(f"Successfully pushed {count} enriched target zones to Firestore.")