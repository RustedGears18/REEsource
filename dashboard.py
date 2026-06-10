import os
import json
import streamlit as st
from google.oauth2 import service_account
from google.cloud import firestore
import pydeck as pdk

# --- Page Config ---
st.set_page_config(page_title="REEsource Target Analytics", layout="wide", page_icon="🌍")

# --- Initialize Firestore ---
@st.cache_resource(show_spinner=False)
def get_db():
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
        cluster_id = data.get('cluster_id')
        
        # Filter out the massive background clusters (noise/baseline)
        if cluster_id in [1, -1, '1', '-1']:
            continue
            
        u_val = data.get('mean_U_ppm', 0)
        
        # Vibrant map scaling: High Uranium is Red, Low Uranium is Yellow
        intensity = min(int((u_val / 20.0) * 255), 255) 
        fill_color = [255, 255 - intensity, 0, 220] 
        
        features.append({
            "type": "Feature",
            "geometry": json.loads(data['geometry']),
            "properties": {
                "cluster_id": cluster_id,
                "min_cluster_size": data.get('min_cluster_size'),
                "mean_U_ppm": data.get('mean_U_ppm'),
                "mean_Th_ppm": data.get('mean_Th_ppm'),
                "mean_K_pct": data.get('mean_K_pct'),
                "mean_Mag_nT": data.get('mean_Mag_nT'),
                "fill_color": fill_color
            }
        })
    return {"type": "FeatureCollection", "features": features}

# --- Application UI ---
st.title("REEsource: Critical Mineral Anomaly Detection")
st.markdown("Interactive exploration of geospatial HDBSCAN clusters highlighting multi-dimensional REE signatures.")

with st.spinner("Initializing geospatial data warehouse..."):
    master_geojson = load_all_targets()

if not master_geojson['features']:
    st.error("Data pipeline connection failed or no valid targets found after filtering.")
    st.stop()

# --- Sidebar Controls ---
st.sidebar.header("Baseline Raster Layers")
st.sidebar.caption("Toggle exported .tif overlays (rendered as bounds)")

show_u_layer = st.sidebar.checkbox("Uranium (U) Baseline")
show_th_layer = st.sidebar.checkbox("Thorium (Th) Baseline")
show_k_layer = st.sidebar.checkbox("Potassium (K) Baseline")
show_mag_layer = st.sidebar.checkbox("RTP Magnetic Baseline")

st.sidebar.divider()
st.sidebar.header("Target Filters")

available_sizes = sorted(list(set([f['properties']['min_cluster_size'] for f in master_geojson['features']])), reverse=True)

selected_size = st.sidebar.select_slider(
    "Algorithmic Granularity (Min Cluster Size)",
    options=available_sizes,
    value=available_sizes[len(available_sizes)//2] if available_sizes else None,
    help="Higher values show massive regional formations. Lower values reveal localized hotspots."
)

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

# --- PyDeck Layers Setup ---
layers = []

# PASTE THE EXACT ARRAY YOUR PYTHON SCRIPT PRINTED HERE
RASTER_BOUNDS = [-107.0, 38.0, -104.0, 40.0] 

# Base URL for public GCS objects
GCS_BASE_URL = "https://storage.googleapis.com/reesource-data-raw"

# Baseline Raster Layers
if show_u_layer:
    layers.append(pdk.Layer(
        "BitmapLayer",
        image=f"{GCS_BASE_URL}/u_baseline.png", 
        bounds=RASTER_BOUNDS,
        opacity=0.6,
        pickable=False
    ))

if show_th_layer:
    layers.append(pdk.Layer(
        "BitmapLayer",
        image=f"{GCS_BASE_URL}/th_baseline.png", 
        bounds=RASTER_BOUNDS,
        opacity=0.6,
        pickable=False
    ))

if show_k_layer:
    layers.append(pdk.Layer(
        "BitmapLayer",
        image=f"{GCS_BASE_URL}/k_baseline.png", 
        bounds=RASTER_BOUNDS,
        opacity=0.6,
        pickable=False
    ))

if show_mag_layer:
    layers.append(pdk.Layer(
        "BitmapLayer",
        image=f"{GCS_BASE_URL}/rtp_mag_baseline.png", 
        bounds=RASTER_BOUNDS,
        opacity=0.6,
        pickable=False
    ))

# HDBSCAN Cluster GeoJSON Layer
layers.append(pdk.Layer(
    "GeoJsonLayer",
    data=filtered_geojson,
    opacity=0.85,
    stroked=True,
    filled=True,
    extruded=True,
    get_elevation="properties.mean_U_ppm * 500", 
    get_fill_color="properties.fill_color",
    get_line_color=[255, 255, 255, 200],
    get_line_width=100, 
    line_width_min_pixels=2,
    pickable=True,
))

# --- Render Map ---
view_state = pdk.ViewState(latitude=39.0, longitude=-105.5, zoom=6.5, pitch=45)

st.pydeck_chart(pdk.Deck(
    api_keys={"mapbox": st.secrets["MAPBOX_API_KEY"]},
    map_provider="mapbox",
    map_style=pdk.map_styles.SATELLITE, 
    layers=layers,
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Uranium:</b> {mean_U_ppm} ppm <br/>"
                "<b>Thorium:</b> {mean_Th_ppm} ppm <br/>"
                "<b>Potassium:</b> {mean_K_pct} % <br/>"
                "<b>Magnetics:</b> {mean_Mag_nT} nT",
        "style": {"backgroundColor": "#333333", "color": "white"}
    }
))