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
def load_all_targets(target_collection, survey_source):
    db = get_db()
    
    # Filter directly at the database level!
    docs = db.collection(target_collection).where("survey_source", "==", survey_source).stream()
    
    features = []
    
    for doc in docs:
        data = doc.to_dict()
        cluster_id = data.get('cluster_id')
        if cluster_id in [1, -1, '1', '-1']:
            continue
            
        # 1. Pop the geometry string out of the data dictionary and load it
        geom_str = data.pop('geometry', None)
        if not geom_str:
            continue
        geom = json.loads(geom_str)

        # Extract values for color logic (allowing them to remain None)
        u_val = data.get('mean_U_ppm')
        th_val = data.get('mean_Th_ppm')
        k_val = data.get('mean_K_pct')
        mag_val = data.get('mean_Mag_nT')

        # 2. Dynamically calculate intensity and color based on the active dimension
        if u_val is not None:
            intensity = min(int((u_val / 20.0) * 255), 255)
            data['fill_color'] = [intensity, 0, 255 - intensity, 140]  # Purple/Red for Master & Uranium
        elif th_val is not None:
            intensity = min(int((th_val / 40.0) * 255), 255)
            data['fill_color'] = [0, intensity, 255 - intensity, 140]  # Cyan for Thorium
        elif k_val is not None:
            intensity = min(int((k_val / 5.0) * 255), 255)
            data['fill_color'] = [intensity, intensity, 0, 140]        # Yellow for Potassium
        elif mag_val is not None:
            intensity = min(int((abs(mag_val) / 500.0) * 255), 255)
            data['fill_color'] = [100, 100, intensity, 140]            # Blue for Magnetics
        else:
            data['fill_color'] = [128, 128, 128, 140]                  # Fallback Gray 
        
        # 3. Append the feature, passing the ENTIRE modified data dictionary as properties!
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": data 
        })
        
    return {"type": "FeatureCollection", "features": features}

@st.cache_data(ttl=86400, show_spinner=False)
def load_region_rasters(active_region):
    db = get_db()
    docs = db.collection('raster_assets').stream()
    assets = {}
    for doc in docs:
        # Dynamically check if 'co_mid' or 'co_ne' is in the asset name
        if active_region.lower() in doc.id.lower():
            assets[doc.id] = doc.to_dict()
    return assets

@st.cache_data(ttl=86400, show_spinner=False)
def load_cmb_mid_rasters():
    db = get_db()
    docs = db.collection('raster_assets').stream()
    assets = {}
    for doc in docs:
        if 'cmb_mid' in doc.id.lower():
            assets[doc.id] = doc.to_dict()
    return assets
