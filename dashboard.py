import streamlit as st
import pydeck as pdk
import pandas as pd
from src.data_fetch import load_all_targets, load_cmb_mid_rasters
from src.map_builder import generate_map_layers

# --- Page Config ---
st.set_page_config(page_title="REEsource Target Analytics", layout="wide", page_icon="🌍")

# --- Application UI ---
st.title("REEsource: Critical Mineral Anomaly Detection")
st.markdown("Interactive exploration of geospatial HDBSCAN clusters highlighting multi-dimensional REE signatures.")

# --- Sidebar Controls (Data Pipeline Source) ---
st.sidebar.header("Data Pipeline Source")

collection_map = {
    "Master Composite (4D)": "target_zones_master",
    "Uranium Isolated (1D)": "target_zones_U",
    "Thorium Isolated (1D)": "target_zones_Th",
    "Potassium Isolated (1D)": "target_zones_K",
    "Magnetic Isolated (1D)": "target_zones_Mag"
}

selected_source_label = st.sidebar.selectbox(
    "Select Active Detection Model", 
    list(collection_map.keys()), 
    index=0
)
target_collection = collection_map[selected_source_label]

with st.spinner(f"Fetching clusters from {target_collection}..."):
    master_geojson = load_all_targets(target_collection)
    raster_assets = load_cmb_mid_rasters()

if not master_geojson['features'] and not raster_assets:
    st.error(f"Data pipeline connection failed or no assets discovered in {target_collection}.")
    st.stop()

# --- Sidebar Controls (Map Config) ---
st.sidebar.divider()
st.sidebar.header("Map Configuration")

map_styles = {
    "Light Mode": "mapbox://styles/mapbox/light-v11",
    "Dark Mode (High Contrast)": "mapbox://styles/mapbox/dark-v11",
    "Satellite": "mapbox://styles/mapbox/satellite-v9",
    "Outdoors/Terrain": "mapbox://styles/mapbox/outdoors-v12",
    "Standard Road Map": "mapbox://styles/mapbox/streets-v12"
}

selected_style_name = st.sidebar.selectbox("Basemap Style", list(map_styles.keys()), index=0)
current_map_style = map_styles[selected_style_name]

# --- Layer Directory ---
st.sidebar.divider()
st.sidebar.header("Layer Directory")

# Opacity slider 
raster_opacity = st.sidebar.slider("Raster Overlay Opacity", min_value=0.0, max_value=1.0, value=0.1, step=0.05)

# Compile Metadata Options
unique_runs = list(set([
    (f['properties']['min_cluster_size'], f['properties']['epsilon']) 
    for f in master_geojson['features'] 
    if f['properties'].get('min_cluster_size') is not None and f['properties'].get('epsilon') is not None
]))
unique_runs.sort(key=lambda x: (-x[0], x[1]))

hd_run_map, raster_run_map = {}, {}
vector_options = ["None"]
raster_options = ["None"]

# Build Vector Options
for r in unique_runs:
    label = f"HDBSCAN: Size {r[0]} | ε {r[1]}"
    vector_options.append(label)
    hd_run_map[label] = r

# Build Raster Options (Unrestricted)
for asset_id, data in raster_assets.items():
    display_name = data.get('name', asset_id.replace('_', ' ').title())
    label = display_name
    raster_options.append(label)
    raster_run_map[label] = data

# --- The Independent Dropdowns ---
# 1. Safely find the index for the default Raster Overlay, fallback to 0 ("None") if not found
default_raster_name = "Equivalent Thorium (Th)"
raster_idx = raster_options.index(default_raster_name) if default_raster_name in raster_options else 0
selected_raster = st.sidebar.selectbox("1. Active Raster Overlay", options=raster_options, index=raster_idx)

# 2. Safely find the index for the default Target Zone, fallback to 0 ("None") if not found
default_vector_name = "HDBSCAN: Size 25 | ε 0.2"
vector_idx = vector_options.index(default_vector_name) if default_vector_name in vector_options else 0
selected_vector = st.sidebar.selectbox("2. Active Target Zones", options=vector_options, index=vector_idx)

# --- Process Layers ---
layers, feature_count = generate_map_layers(
    selected_vector, selected_raster, hd_run_map, raster_run_map, master_geojson, raster_opacity
)

if selected_vector != "None":
    st.sidebar.success(f"**{feature_count}** Target Anomaly Zones isolated from {selected_source_label}.")
if selected_raster != "None":
    st.sidebar.info("Raster Overlay active.")

# --- Render Map ---
view_state = pdk.ViewState(
    latitude=38.2645,
    longitude=-107.0778, 
    zoom=12.0, 
    min_zoom=4.0,   
    max_zoom=15.0
)

st.pydeck_chart(pdk.Deck(
    map_provider="mapbox",
    map_style=current_map_style, 
    layers=layers,
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Target Area:</b> ~{width_km} km x {height_km} km <br/>"
                "<hr/>"
                "<b>Primary Score (DBCV):</b> {dbcv_score}",
        "style": {"backgroundColor": "#333333", "color": "white", "font-family": "sans-serif", "fontSize": "14px"}
    }
))

# --- Detailed Metrics Data Grid ---
st.divider()
st.subheader("Target Zone Analytics")

if master_geojson and master_geojson.get('features'):
    properties_list = [feature['properties'] for feature in master_geojson['features']]
    
    if properties_list:
        df_metrics = pd.DataFrame(properties_list)
        
        # dbcv_score is already here, so it will automatically sort to the front!
        ideal_core_cols = ['cluster_id', 'survey_source', 'dbcv_score', 'z_score', 'p_value', 'primary_tested_dim']
        core_cols = [col for col in ideal_core_cols if col in df_metrics.columns]
        
        # Added width_km and height_km to the exclusion list here
        cols_to_exclude = ['geometry', 'fill_color', 'width_km', 'height_km']
        dynamic_cols = [col for col in df_metrics.columns if col not in core_cols and col not in cols_to_exclude]
        
        df_metrics = df_metrics[core_cols + dynamic_cols]
        
        st.dataframe(
            df_metrics,
            use_container_width=True,
            height=300
        )
else:
    st.info("No target zone data available to display in the metrics table.")
else:
    st.info("No target zone data available to display in the metrics table.")