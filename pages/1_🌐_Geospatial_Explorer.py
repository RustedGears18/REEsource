import os
from dotenv import load_dotenv

# 1. LOAD LOCAL CREDENTIALS (Ignored by Streamlit Cloud)
load_dotenv()

# 2. IMPORT LIBRARIES
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
from pyproj import Transformer
from google.cloud import firestore
from google.oauth2 import service_account
import leafmap.foliumap as leafmap

# Configure the page
st.set_page_config(page_title="Geospatial Explorer", page_icon="🌐", layout="wide")

# --- INITIALIZATION & CACHING ---
@st.cache_resource
def get_firestore_client():
    """Initializes Firestore client securely for both Local and Cloud environments."""
    try:
        # Check if we are running on Streamlit Cloud
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"]
            )
            return firestore.Client(credentials=creds, project=creds.project_id)
        else:
            # Fallback for local development
            return firestore.Client()
    except Exception as e:
        st.error(f"Firestore Initialization Error: {e}")
        return None

db = get_firestore_client()

def fetch_surveys():
    """Retrieves the parent Earth MRI surveys from Firestore."""
    if not db: return []
    docs = db.collection("usgs_surveys").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

def fetch_assets_for_survey(survey_id):
    """Retrieves available raster layers for a specific survey."""
    if not db: return []
    docs = db.collection("raster_assets").where("parent_survey_id", "==", survey_id).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

@st.cache_data(show_spinner=False)
def calculate_contrast_stretch(target_uri):
    """Reads a low-res thumbnail of the COG and calculates the 2nd-98th percentile."""
    try:
        with rasterio.open(target_uri) as src:
            thumbnail = src.read(1, out_shape=(1, 500, 500))
            nodata = src.nodata if src.nodata is not None else 0
            valid_pixels = thumbnail[thumbnail != nodata]
            
            if valid_pixels.size > 0:
                vmin = float(np.percentile(valid_pixels, 2))
                vmax = float(np.percentile(valid_pixels, 98))
                return vmin, vmax
            else:
                return None, None
    except Exception as e:
        st.warning(f"Using default stretch. Could not calculate dynamic scale: {e}")
        return None, None

@st.cache_data(show_spinner=False)
def load_and_project_anomalies(file_path):
    """Loads ML targets and translates UTM 13N projected meters to WGS84 GPS degrees."""
    if not os.path.exists(file_path):
        return None
        
    df = pd.read_csv(file_path)
    
    # EPSG:26913 = NAD83 / UTM zone 13N (Colorado standard)
    # EPSG:4326 = WGS84 standard web map GPS
    transformer = Transformer.from_crs("EPSG:26913", "EPSG:4326", always_xy=True)
    
    # Project the arrays on the fly
    df['lon_wgs84'], df['lat_wgs84'] = transformer.transform(
        df['Longitude'].values, 
        df['Latitude'].values
    )
    
    return df

# --- MAIN APPLICATION LOGIC ---
def main():
    st.title("🌐 Geospatial Explorer")
    st.markdown("Explore high-resolution Earth MRI raster payloads via Cloud Optimized GeoTIFFs.")
    st.divider()

    # Fetch Catalog Data
    surveys = fetch_surveys()
    if not surveys:
        st.warning("No survey metadata found. Ensure your Firestore catalog is seeded.")
        return

    # --- SIDEBAR: DATA CATALOG ---
    st.sidebar.header("Data Catalog")
    
    survey_options = {s["survey_name"]: s["id"] for s in surveys}
    selected_survey_name = st.sidebar.selectbox("1. Target Region", list(survey_options.keys()))
    selected_survey_id = survey_options[selected_survey_name]

    assets = fetch_assets_for_survey(selected_survey_id)
    if not assets:
        st.sidebar.warning("No raster layers found for this region.")
        return

    asset_options = {f"{a['layer_type'].title()}: {a['proxy_metric']}": a for a in assets}
    selected_asset_label = st.sidebar.selectbox("2. Geophysical Payload", list(asset_options.keys()))
    target_asset = asset_options[selected_asset_label]

    # For rasterio calculations (requires /vsigs/ to read metadata over GCP)
    gdal_uri = target_asset.get("storage_uri").replace("gs://", "/vsigs/")
    
    # For Streamlit Cloud map rendering (requires standard HTTP to bypass port blockers)
    http_uri = target_asset.get("storage_uri").replace("gs://", "https://storage.googleapis.com/")

    # --- MAIN VIEW ---
    if gdal_uri and http_uri:
        col1, col2 = st.columns([3, 1])

        with col1:
            st.subheader(selected_asset_label)
            
            # Interactive Mapping Controls
            ctrl1, ctrl2 = st.columns(2)
            with ctrl1:
                opacity = st.slider("Layer Opacity", min_value=0.0, max_value=1.0, value=0.6, step=0.05)
            with ctrl2:
                default_cmap = "magma" if target_asset['layer_type'] == "radiometric" else "viridis"
                colormap = st.selectbox("Style Palette", ["magma", "viridis", "plasma", "inferno", "terrain"], index=0 if default_cmap == "magma" else 1)

            with st.spinner("Analyzing array distribution..."):
                vmin, vmax = calculate_contrast_stretch(gdal_uri)

            # Map Rendering
            m = leafmap.Map(google_map="HYBRID", draw_control=False, measure_control=False)
            
            try:
                # 1. Mount the Heavy Cloud Optimized GeoTIFF via HTTP
                m.add_cog(
                    http_uri, 
                    cmap=colormap, 
                    opacity=opacity, 
                    layer_name=target_asset['proxy_metric']
                )
                
                # 2. Overlay the Machine Learning Targets
                anomaly_csv_path = os.path.join("data", "processed", "cmb_mid_2023_anomalies.csv")
                anomalies_df = load_and_project_anomalies(anomaly_csv_path)

                if anomalies_df is not None and not anomalies_df.empty:
                    m.add_points_from_xy(
                        anomalies_df,
                        x="lon_wgs84",
                        y="lat_wgs84",
                        popup=["Anomaly_Score", "eTh_Raw", "RTP_Raw"], 
                        icon_names=['circle'],
                        spin=True,
                        add_legend=True,
                        layer_name="FJH Feedstock Anomalies"
                    )
                
                m.to_streamlit(height=650)
                
            except Exception as e:
                st.error(f"Render Error. Details: {e}")

        # --- METADATA PANEL ---
        with col2:
            st.markdown("### Layer Profile")
            st.info(
                f"**Survey:** {selected_survey_name}\n\n"
                f"**Category:** {target_asset['layer_type'].title()}\n\n"
                f"**Proxy Metric:** {target_asset['proxy_metric']}\n\n"
                f"**Status:** {target_asset.get('processing_status', 'Unknown')}"
            )
            
            if vmin and vmax:
                st.markdown("### Contrast Stretch")
                st.caption(f"**Min (2nd Pctl):** `{vmin:.2f}`")
                st.caption(f"**Max (98th Pctl):** `{vmax:.2f}`")

            st.markdown("### Interpretation")
            if target_asset['layer_type'] == "radiometric":
                st.write("Radiometric surveys detect gamma-ray emissions. High Thorium (eTh) often acts as a proxy indicator for REE-bearing carbonatite intrusions.")
            else:
                st.write("Magnetic surveys detect variations caused by deep rock formations. Used to map the physical geometry and boundaries of igneous intrusions.")

if __name__ == "__main__":
    main()