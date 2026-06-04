import os
import json
import tempfile
from datetime import timedelta
from dotenv import load_dotenv

# 1. LOAD LOCAL CREDENTIALS (Ignored by Streamlit Cloud)
load_dotenv()

# 2. IMPORT LIBRARIES
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
from pyproj import Transformer
from google.cloud import firestore, storage
from google.oauth2 import service_account
import leafmap.foliumap as leafmap

# Configure the page
st.set_page_config(page_title="Geospatial Explorer", page_icon="🌐", layout="wide")

# --- CLOUD AUTHENTICATION INJECTION ---
@st.cache_resource
def inject_gcp_credentials():
    """Writes Streamlit secrets to an ephemeral JSON file for secure GCP authentication."""
    if "gcp_service_account" in st.secrets and "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, 'w') as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
        return True
    return False

inject_gcp_credentials()

# --- INITIALIZATION & CACHING ---
@st.cache_resource
def get_firestore_client():
    try:
        return firestore.Client()
    except Exception as e:
        st.error(f"Firestore Initialization Error: {e}")
        return None

db = get_firestore_client()

def fetch_surveys():
    if not db: return []
    docs = db.collection("usgs_surveys").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

def fetch_assets_for_survey(survey_id):
    if not db: return []
    docs = db.collection("raster_assets").where("parent_survey_id", "==", survey_id).stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

@st.cache_data(show_spinner=False)
def calculate_contrast_stretch(target_uri):
    try:
        with rasterio.open(target_uri) as src:
            thumbnail = src.read(1, out_shape=(1, 500, 500))
            nodata = src.nodata if src.nodata is not None else 0
            valid_pixels = thumbnail[thumbnail != nodata]
            if valid_pixels.size > 0:
                return float(np.percentile(valid_pixels, 2)), float(np.percentile(valid_pixels, 98))
            return None, None
    except Exception as e:
        st.warning(f"Could not calculate dynamic scale: {e}")
        return None, None

@st.cache_data(show_spinner=False)
def load_and_project_anomalies(file_path):
    if not os.path.exists(file_path):
        return None
    df = pd.read_csv(file_path)
    transformer = Transformer.from_crs("EPSG:26913", "EPSG:4326", always_xy=True)
    df['lon_wgs84'], df['lat_wgs84'] = transformer.transform(df['Longitude'].values, df['Latitude'].values)
    return df

def generate_signed_url(gs_uri):
    """Generates a secure, 1-hour signed URL to allow TiTiler to stream the private raster."""
    bucket_name = gs_uri.split("/")[2]
    blob_name = "/".join(gs_uri.split("/")[3:])
    
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    return blob.generate_signed_url(version="v4", expiration=timedelta(hours=1), method="GET")

# --- MAIN APPLICATION LOGIC ---
def main():
    st.title("🌐 Geospatial Explorer")
    st.markdown("Explore high-resolution Earth MRI raster payloads via Cloud Optimized GeoTIFFs.")
    st.divider()

    surveys = fetch_surveys()
    if not surveys:
        st.warning("No survey metadata found. Ensure your Firestore catalog is seeded.")
        return

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

    # URIs
    raw_gs_uri = target_asset.get("storage_uri")
    gdal_uri = raw_gs_uri.replace("gs://", "/vsigs/")

    if raw_gs_uri:
        col1, col2 = st.columns([3, 1])

        with col1:
            st.subheader(selected_asset_label)
            
            ctrl1, ctrl2 = st.columns(2)
            with ctrl1:
                opacity = st.slider("Layer Opacity", min_value=0.0, max_value=1.0, value=0.6, step=0.05)
            with ctrl2:
                default_cmap = "magma" if target_asset['layer_type'] == "radiometric" else "viridis"
                colormap = st.selectbox("Style Palette", ["magma", "viridis", "plasma", "inferno", "terrain"], index=0 if default_cmap == "magma" else 1)

            with st.spinner("Analyzing array distribution & Generating Secure Stream..."):
                vmin, vmax = calculate_contrast_stretch(gdal_uri)
                # Create the signed URL for the public TiTiler proxy
                signed_http_uri = generate_signed_url(raw_gs_uri)

            # Center map on Colorado and set zoom level to prevent the "world view" bug
            m = leafmap.Map(center=[39.0, -105.0], zoom=7, google_map="HYBRID", draw_control=False, measure_control=False)
            
            try:
                # 1. Mount the Secure Signed URL
                m.add_cog_layer(
                    signed_http_uri, 
                    colormap_name=colormap, 
                    opacity=opacity, 
                    name=target_asset['proxy_metric']
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
                        layer_name="FJH Feedstock Anomalies" # Adds directly to layer control
                    )
                else:
                    st.warning("⚠️ ML Targets CSV not found. Ensure cmb_mid_2023_anomalies.csv is pushed to GitHub.")
                
                # Expose the layer control icon on the map
                m.add_layer_control()
                
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

if __name__ == "__main__":
    main()