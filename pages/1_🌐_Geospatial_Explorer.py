import os
import json
import tempfile
from datetime import timedelta
from dotenv import load_dotenv

# 1. LOAD LOCAL CREDENTIALS (Ignored by Streamlit Cloud)
load_dotenv()

# 2. IMPORT LIBRARIES
import pandas as pd
import streamlit as st
from pyproj import Transformer
from google.cloud import firestore, storage
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
def load_and_project_anomalies(file_path):
    """Loads scikit-learn targets and projects them to WGS84 for web mapping."""
    if not os.path.exists(file_path):
        return None
    df = pd.read_csv(file_path)
    transformer = Transformer.from_crs("EPSG:26913", "EPSG:4326", always_xy=True)
    df['lon_wgs84'], df['lat_wgs84'] = transformer.transform(df['Longitude'].values, df['Latitude'].values)
    return df

def generate_signed_url(gs_uri):
    """Generates a secure, 1-hour signed URL to allow Leafmap to stream the private raster."""
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

    if raw_gs_uri:
        col1, col2 = st.columns([3, 1])

        with col1:
            st.subheader(selected_asset_label)
            
            # Simplified controls since the raster is already colored
            opacity = st.slider("Layer Opacity", min_value=0.0, max_value=1.0, value=0.6, step=0.05)

            with st.spinner("Generating Secure Stream..."):
                # Generate the raw signed URL
                raw_signed_url = generate_signed_url(raw_gs_uri)

            # Center map on Colorado Mineral Belt
            m = leafmap.Map(center=[39.0, -105.0], zoom=7, google_map="HYBRID", draw_control=False, measure_control=False)
            
            try:
                # Direct COG rendering via Leafmap (Native RGB handling)
                m.add_cog_layer(
                    url=raw_signed_url,
                    name=target_asset['proxy_metric'],
                    opacity=opacity
                )
                
                # Overlay the Machine Learning Targets
                anomaly_csv_path = os.path.join("data", "processed", "cmb_mid_2023_anomalies.csv")
                anomalies_df = load_and_project_anomalies(anomaly_csv_path)

                if anomalies_df is not None and not anomalies_df.empty:
                    m.add_circle_markers_from_xy(
                        anomalies_df,
                        x="lon_wgs84",
                        y="lat_wgs84",
                        radius=5,          
                        color="red",       
                        fill_color="red",  
                        fill_opacity=0.7,
                        popup=["Anomaly_Score", "eTh_Raw", "RTP_Raw"], 
                        layer_name="Anomaly Targets"
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

if __name__ == "__main__":
    main()