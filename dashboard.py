import streamlit as st
import pydeck as pdk
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

st.sidebar.divider()
st.sidebar.header("Layer Directory")

# Compile Metadata Options
unique_runs = list(set([
    (f['properties']['min_cluster_size'], f['properties']['epsilon']) 
    for f in master_geojson['features'] 
    if f['properties'].get('min_cluster_size') is not None and f['properties'].get('epsilon') is not None
]))
unique_runs.sort(key=lambda x: (-x[0], x[1]))

dropdown_options = []
hd_run_map, raster_run_map = {}, {}

for r in unique_runs:
    label = f"HDBSCAN: Size {r[0]} | ε {r[1]}"
    dropdown_options.append(label)
    hd_run_map[label] = r

for asset_id, data in raster_assets.items():
    display_name = data.get('name', asset_id.replace('_', ' ').title())
    label = f"Raster Overlay: {display_name}"
    dropdown_options.append(label)
    raster_run_map[label] = data

selected_layer_label = st.sidebar.selectbox("Select Active Display Layer", options=dropdown_options)

# --- Process Layers ---
layers, feature_count, layer_type = generate_map_layers(
    selected_layer_label, hd_run_map, raster_run_map, master_geojson
)

if layer_type == "vector":
    st.sidebar.success(f"**{feature_count}** Target Anomaly Zones isolated from {selected_source_label}.")
elif layer_type == "raster":
    st.sidebar.success("Selected Raster Overlay active.")

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
    tooltip={
        "html": "<b>Cluster ID:</b> {cluster_id} <br/>"
                "<b>Dimensions:</b> ~{width_km} km x {height_km} km <br/>"
                "<hr/>"
                "<b>Uranium:</b> {mean_U_ppm} ppm <br/>"
                "<b>Thorium:</b> {mean_Th_ppm} ppm <br/>"
                "<b>Potassium:</b> {mean_K_pct} % <br/>"
                "<b>Magnetics:</b> {mean_Mag_nT} nT <br/>"
                "<br/>"
                "<b>Run Specs:</b> Min Size {min_cluster_size} | ε {epsilon}<br/>"
                "<b>DBCV Score:</b> {dbcv_score}",
        "style": {"backgroundColor": "#333333", "color": "white", "font-family": "sans-serif"}
    }
))