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
        
    raw_secret_string = st.secrets["gcp_service_account"]
    creds_dict = json.loads(raw_secret_string)
        
    credentials = service_account.Credentials.from_service_account_info(creds_dict)
    return firestore.Client(credentials=credentials, project=creds_dict["project_id"])

db = get_db()

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
                "epsilon": data.get('epsilon'), 
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
    """Fetches raster metadata from Firestore where document ID contains 'cmb_mid'"""
    docs = db.collection('raster_assets').stream()
    assets = {}
    
    for doc in docs:
        if 'cmb_mid' in doc.id.lower():
            assets[doc.id] = doc.to_dict()
            
    return assets

# --- Application UI ---
st.title("REEsource: Critical Mineral Anomaly Detection")
st.markdown("Interactive exploration of geospatial HDBSCAN clusters highlighting multi-dimensional REE signatures.")

with st.spinner("Initializing geospatial data warehouse..."):
    master_geojson = load_all_targets()
    raster_assets = load_cmb_mid_rasters()

if not master_geojson['features']:
    st.error("Data pipeline connection failed or no valid targets found after filtering.")
    st.stop()

# --- Sidebar Controls ---
st.sidebar.header("Map Configuration")

map_styles = {
    "Dark Mode (High Contrast)": "mapbox://styles/mapbox/dark-v11",
    "Satellite": "mapbox://styles/mapbox/satellite-v9",
    "Light Mode": "mapbox://styles/mapbox/light-v11",
    "Outdoors/Terrain": "mapbox://styles/mapbox/outdoors-v12",
    "Standard Road Map": "mapbox://styles/mapbox/streets-v12"
}

selected_style_name = st.sidebar.selectbox("Basemap Style", list(map_styles.keys()), index=0)
current_map_style = map_styles[selected_style_name]

# Dynamic Raster Layers based on Firestore 'cmb_mid' documents
st.sidebar.divider()
st.sidebar.header("CMB Mid Raster Layers")
st.sidebar.caption("Toggle dynamically loaded raster overlays")

active_rasters = {}
if not raster_assets:
    st.sidebar.warning("No 'cmb_mid' assets found in Firestore.")
else:
    for asset_id, data in raster_assets.items():
        display_name = data.get('name', asset_id.replace('_', ' ').title())
        if st.sidebar.checkbox(f"Show {display_name}"):
            active_rasters[asset_id] = data

st.sidebar.divider()
st.sidebar.header("HDBSCAN Target Layers")

# Extract unique run configurations dynamically (combining Size and Epsilon)
unique_runs = list(set([
    (f['properties']['min_cluster_size'], f['properties']['epsilon']) 
    for f in master_geojson['features'] 
    if f['properties'].get('min_cluster_size') is not None and f['properties'].get('epsilon') is not None
]))

# Sort them logically: primarily by Size (descending), then by Epsilon (ascending)
unique_runs.sort(key=lambda x: (-x[0], x[1]))

# Create formatted labels for the dropdown list
run_labels = [f"Run: Size {r[0]} | ε {r[1]}" for r in unique_runs]

if not run_labels:
    st.sidebar.error("No valid HDBSCAN run metadata found in targets.")
    st.stop()

# Single dropdown to move through the layers
selected_label = st.sidebar.selectbox("Select Output Layer", options=run_labels)

# Map the selected label back to the actual size and epsilon values
selected_index = run_labels.index(selected_label)
selected_size, selected_epsilon = unique_runs[selected_index]


# --- In-Memory Filtering (Simplified) ---
filtered_features = [
    f for f in master_geojson['features']
    if f['properties']['min_cluster_size'] == selected_size
    and f['properties']['epsilon'] == selected_epsilon
]

filtered_geojson = {"type": "FeatureCollection", "features": filtered_features}
st.sidebar.success(f"**{len(filtered_features)}** Target Zones visible.")

# --- PyDeck Layers Setup ---
layers = []

# Process dynamically fetched CMB Mid Raster Assets
for asset_id, data in active_rasters.items():
    url = data.get('url') or data.get('image_url')
    bounds = data.get('bounds')
    
    if url and bounds:
        layers.append(pdk.Layer(
            "BitmapLayer",
            id=f"raster_{asset_id}", 
            image=url, 
            bounds=bounds,
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
# Centered directly on Blue Mesa Reservoir
view_state = pdk.ViewState(
    latitude=38.4733, 
    longitude=-107.1944, 
    zoom=10.5, 
    min_zoom=6.5,   
    max_zoom=14.0,  
    pitch=45
)

st.pydeck_chart(pdk.Deck(
    api_keys={"mapbox": st.secrets["MAPBOX_API_KEY"]},
    map_provider="mapbox",
    map_style=current_map_style, 
    layers=layers,
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Uranium:</b> {mean_U_ppm} ppm <br/>"
                "<b>Thorium:</b> {mean_Th_ppm} ppm <br/>"
                "<b>Potassium:</b> {mean_K_pct} % <br/>"
                "<b>Magnetics:</b> {mean_Mag_nT} nT <br/>"
                "<b>Algorithm Config:</b> Size {min_cluster_size} | ε {epsilon}",
        "style": {"backgroundColor": "#333333", "color": "white"}
    }
))