import os
import json
import streamlit as st
from google.oauth2 import service_account
from google.cloud import firestore
import pydeck as pdk
import pandas as pd

# --- Page Config ---
st.set_page_config(page_title="REEsource Target Analytics", layout="wide", page_icon="🌍")

# --- Initialize Firestore (Universal Production Auth) ---
@st.cache_resource(show_spinner=False)
def get_db():
    # Gracefully check if secrets exist yet
    if "gcp_service_account" not in st.secrets:
        return None
        
    secret_data = st.secrets["gcp_service_account"]
    
    if isinstance(secret_data, str):
        creds_dict = json.loads(secret_data)
    else:
        creds_dict = dict(secret_data)
        
    credentials = service_account.Credentials.from_service_account_info(creds_dict)
    return firestore.Client(credentials=credentials, project=creds_dict["project_id"])

db = get_db()

# Prevent the rest of the script from running if the database isn't connected
if db is None:
    st.warning("⏳ Infrastructure Provisioning: Awaiting Cloud Run Secrets injection...")
    st.stop()

# --- Fetch & Cache Data ---
@st.cache_data(ttl=86400, show_spinner=False) 
def load_all_targets(collection_name='ree_targets'):
    docs = db.collection(collection_name).stream()
    features = []
    
    for doc in docs:
        data = doc.to_dict()
        u_val = data.get('mean_U_ppm', 0)
        intensity = min(int((u_val / 15.0) * 255), 255)
        
        features.append({
            "type": "Feature",
            "geometry": json.loads(data['geometry']),
            "properties": {
                "cluster_id": data.get('cluster_id'),
                "min_cluster_size": data.get('min_cluster_size'),
                "mean_U_ppm": data.get('mean_U_ppm'),
                "mean_Th_ppm": data.get('mean_Th_ppm'),
                "mean_K_pct": data.get('mean_K_pct'),
                "mean_Mag_nT": data.get('mean_Mag_nT'),
                "fill_color": [intensity, 50, 255 - intensity, 200] 
            }
        })
    return {"type": "FeatureCollection", "features": features}

# --- Application UI ---
st.title("REEsource: Critical Mineral Anomaly Detection")
st.markdown("Interactive exploration of geospatial HDBSCAN clusters highlighting multi-dimensional REE signatures.")

with st.spinner("Initializing geospatial data warehouse..."):
    master_geojson = load_all_targets()

if not master_geojson['features']:
    st.error("Data pipeline connection failed. No targets found.")
    st.stop()

# --- Sidebar Analytics Controls ---
st.sidebar.header("Target Filters")

available_sizes = sorted(list(set([f['properties']['min_cluster_size'] for f in master_geojson['features']])), reverse=True)

selected_size = st.sidebar.select_slider(
    "Algorithmic Granularity (Min Cluster Size)",
    options=available_sizes,
    value=available_sizes[len(available_sizes)//2],
    help="Higher values show massive regional formations. Lower values reveal localized hotspots."
)

st.sidebar.divider()
st.sidebar.subheader("Geochemical Thresholds")

min_u = st.sidebar.slider("Minimum Uranium (ppm)", 0.0, 20.0, 0.0, 0.5)
min_th = st.sidebar.slider("Minimum Thorium (ppm)", 0.0, 40.0, 0.0, 1.0)
max_mag = st.sidebar.slider("Maximum Magnetic Anomaly (nT)", -1000, 2000, 2000, 100)

# --- In-Memory Filtering ---
filtered_features = [
    f for f in master_geojson['features']
    if f['properties']['min_cluster_size'] == selected_size
    and f['properties']['mean_U_ppm'] >= min_u
    and f['properties']['mean_Th_ppm'] >= min_th
    and f['properties']['mean_Mag_nT'] <= max_mag
]

filtered_geojson = {"type": "FeatureCollection", "features": filtered_features}

st.sidebar.success(f"**{len(filtered_features)}** Target Zones visible.")

# --- PyDeck Visualization ---
view_state = pdk.ViewState(latitude=39.0, longitude=-105.5, zoom=6.5, pitch=45)

geojson_layer = pdk.Layer(
    "GeoJsonLayer",
    data=filtered_geojson,
    opacity=0.8,
    stroked=True,
    filled=True,
    extruded=True,
    get_elevation="properties.mean_U_ppm * 500", 
    get_fill_color="properties.fill_color",
    get_line_color=[255, 255, 255, 150],
    get_line_width=50,
    line_width_min_pixels=1,
    pickable=True,
)

st.pydeck_chart(pdk.Deck(
    # Pulling Mapbox API key from Streamlit secrets as well
    api_keys={"mapbox": st.secrets["MAPBOX_API_KEY"]},
    map_provider="mapbox",
    map_style=pdk.map_styles.SATELLITE, 
    layers=[geojson_layer],
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Uranium:</b> {mean_U_ppm} ppm <br/>"
                "<b>Thorium:</b> {mean_Th_ppm} ppm <br/>"
                "<b>Potassium:</b> {mean_K_pct} % <br/>"
                "<b>Magnetics:</b> {mean_Mag_nT} nT",
        "style": {"backgroundColor": "steelblue", "color": "white"}
    }
))