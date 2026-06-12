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
@st.cache_data(ttl=86400, show_spinner=True) 
def load_all_targets(collection_name='ree_targets'):
    docs = db.collection(collection_name).stream()
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

if not master_geojson['features'] and not raster_assets:
    st.error("Data pipeline connection failed or no assets discovered.")
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

st.sidebar.divider()
st.sidebar.header("Layer Directory")

# Compile HDBSCAN Run metadata options
unique_runs = list(set([
    (f['properties']['min_cluster_size'], f['properties']['epsilon']) 
    for f in master_geojson['features'] 
    if f['properties'].get('min_cluster_size') is not None and f['properties'].get('epsilon') is not None
]))
unique_runs.sort(key=lambda x: (-x[0], x[1]))

# Build master lists for unified option toggling
dropdown_options = []
hd_run_map = {}
raster_run_map = {}

for r in unique_runs:
    label = f"HDBSCAN: Size {r[0]} | ε {r[1]}"
    dropdown_options.append(label)
    hd_run_map[label] = r

for asset_id, data in raster_assets.items():
    display_name = data.get('name', asset_id.replace('_', ' ').title())
    label = f"Raster Overlay: {display_name}"
    dropdown_options.append(label)
    raster_run_map[label] = data

# Single selector moving one-by-one through data layers
selected_layer_label = st.sidebar.selectbox("Select Active Display Layer", options=dropdown_options)

# --- PyDeck Layers Processing ---
layers = []

if selected_layer_label in hd_run_map:
    target_size, target_epsilon = hd_run_map[selected_layer_label]
    filtered_features = [
        f for f in master_geojson['features']
        if f['properties']['min_cluster_size'] == target_size
        and f['properties']['epsilon'] == target_epsilon
    ]
    filtered_geojson = {"type": "FeatureCollection", "features": filtered_features}
    st.sidebar.success(f"**{len(filtered_features)}** Target Anomaly Zones isolated.")
    
    layers.append(pdk.Layer(
        "GeoJsonLayer",
        data=filtered_geojson,
        opacity=0.65, # Dropped from 0.90 to let the basemap bleed through
        stroked=True,
        filled=True,
        extruded=True,  # Activated 3D extrusion
        wireframe=True, # Adds a subtle 3D mesh look
        
        # Color mapping (Reads the RGBA array from your properties)
        get_fill_color="properties.fill_color",
        
        # Softer, thinner borders (RGBA: light gray, semi-transparent)
        get_line_color=[200, 200, 200, 120], 
        get_line_width=30, # Dropped from 250
        line_width_min_pixels=1,
        
        # 3D Elevation mapping (Scales the physical height by the Uranium PPM)
        get_elevation="properties.mean_U_ppm",
        elevation_scale=50, # Adjust this multiplier to make the 3D effect taller or shorter
        
        pickable=True,
        auto_highlight=True # Highlights the specific polygon when hovered
    ))

elif selected_layer_label in raster_run_map:
    raster_data = raster_run_map[selected_layer_label]
    url = raster_data.get('url') or raster_data.get('image_url')
    bounds = raster_data.get('bounds')
    
    if url and bounds:
        layers.append(pdk.Layer(
            "BitmapLayer",
            id="active_raster_overlay", 
            image=url, 
            bounds=bounds,
            opacity=0.75,
            pickable=False
        ))
        st.sidebar.success("Selected Raster Overlay active.")

# --- Render Map ---
view_state = pdk.ViewState(
    latitude= 38.267, 
    longitude= -107.08, 
    zoom=10.0, 
    min_zoom=5.0,   
    max_zoom=14.0
)

st.pydeck_chart(pdk.Deck(
    api_keys={"mapbox": st.secrets["MAPBOX_API_KEY"]},
    map_provider="mapbox",
    map_style=current_map_style, 
    layers=layers,
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Dimensions:</b> ~{width_km} km x {height_km} km <br/>"
                "<hr/>"
                "<b>Uranium:</b> {mean_U_ppm} ppm <br/>"
                "<b>Thorium:</b> {mean_Th_ppm} ppm <br/>"
                "<b>Potassium:</b> {mean_K_pct} % <br/>"
                "<b>Magnetics:</b> {mean_Mag_nT} nT <br/>"
                "<br/>"
                "<b>Run Specs:</b> Min Size {min_cluster_size} | ε {epsilon}",
        "style": {"backgroundColor": "#333333", "color": "white", "font-family": "sans-serif"}
    }
))