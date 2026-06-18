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
    # Pass the selected collection to your data fetcher
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

# Add the opacity slider right here
raster_opacity = st.sidebar.slider("Raster Overlay Opacity", min_value=0.0, max_value=1.0, value=0.6, step=0.05)

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

# Build Raster Options
for asset_id, data in raster_assets.items():
    display_name = data.get('name', asset_id.replace('_', ' ').title())
    label = display_name
    raster_options.append(label)
    raster_run_map[label] = data

# --- The Independent Dropdowns ---
selected_raster = st.sidebar.selectbox("1. Active Raster Overlay", options=raster_options)
selected_vector = st.sidebar.selectbox("2. Active Target Zones", options=vector_options)

# --- Process Layers ---
# Pass BOTH selections into the map builder
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
    api_keys={"mapbox": st.secrets["MAPBOX_API_KEY"]},
    map_provider="mapbox",
    map_style=current_map_style, 
    layers=layers,
    initial_view_state=view_state,
    # Inside your pdk.Deck definition...
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
    # Extract just the properties (ignoring the complex geometry coordinates)
    properties_list = [feature['properties'] for feature in master_geojson['features']]
    
    if properties_list:
        # Convert to a DataFrame
        df_metrics = pd.DataFrame(properties_list)
        
        # Reorder the columns so the most important identifiers are on the left
        core_cols = ['cluster_id', 'survey_source', 'dbcv_score', 'z_score', 'p_value', 'primary_tested_dim']
        dynamic_cols = [col for col in df_metrics.columns if col not in core_cols and col not in ['geometry', 'fill_color']]
        
        df_metrics = df_metrics[core_cols + dynamic_cols]
        
        # Display as a highly interactive grid
        st.dataframe(
            df_metrics,
            use_container_width=True,
            hide_index=True,
            height=300 # Keeps it contained so you can scroll the table independently
        )
else:
    st.info("No target zone data available to display in the metrics table.")