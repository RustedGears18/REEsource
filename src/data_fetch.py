import json
import streamlit as st
from google.oauth2 import service_account
from google.cloud import firestore

@st.cache_resource(show_spinner=False)
def get_db():
    if "gcp_service_account" not in st.secrets:
        return None
        
    raw_secret_string = st.secrets["gcp_service_account"]
    creds_dict = json.loads(raw_secret_string)
        
    credentials = service_account.Credentials.from_service_account_info(creds_dict)
    return firestore.Client(credentials=credentials, project=creds_dict["project_id"])

@st.cache_data(ttl=86400, show_spinner=True) 
def load_all_targets(target_collection):
    db = get_db()
    docs = db.collection(target_collection).stream()
    features = []
    
    for doc in docs:
        data = doc.to_dict()
        cluster_id = data.get('cluster_id')
        if cluster_id in [1, -1, '1', '-1']:
            continue
            
        geom = json.loads(data['geometry'])
        u_val = data.get('mean_U_ppm', 0)
        intensity = min(int((u_val / 20.0) * 255), 255) 
        fill_color = [255, 255 - intensity, 0, 220] 
        
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "cluster_id": data.get('cluster_id'),
                "min_cluster_size": data.get('min_cluster_size'),
                "epsilon": data.get('epsilon'), 
                "width_km": data.get('width_km', 'N/A'),
                "height_km": data.get('height_km', 'N/A'),
                "mean_U_ppm": data.get('mean_U_ppm'),
                "mean_Th_ppm": data.get('mean_Th_ppm'),
                "mean_K_pct": data.get('mean_K_pct'),
                "mean_Mag_nT": data.get('mean_Mag_nT'),
                "fill_color": fill_color
            }
        })
    return {"type": "FeatureCollection", "features": features}

@st.cache_data(ttl=86400, show_spinner=False)
def load_cmb_mid_rasters():
    db = get_db()
    docs = db.collection('raster_assets').stream()
    assets = {}
    for doc in docs:
        if 'cmb_mid' in doc.id.lower():
            assets[doc.id] = doc.to_dict()
    return assets
