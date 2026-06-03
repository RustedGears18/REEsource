import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
from dotenv import load_dotenv

# We will keep dotenv and basic config for your GCP credentials
load_dotenv()

st.set_page_config(page_title="REEsource Geophysical Dashboard", page_icon="🧲", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1.5rem !important; }
    iframe { height: 82vh !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- FIRESTORE INITIALIZATION ---
def get_firestore_client():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            return firestore.Client.from_service_account_info(creds_dict)
        else:
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            return firestore.Client.from_service_account_json(key_path) if key_path else firestore.Client()
    except Exception as e:
        st.error(f"Firestore Initialization Error: {e}")
        return None

db = get_firestore_client()

def main():
    st.sidebar.title("🌍 REEsource Earth MRI")
    st.sidebar.divider()

    # --- SIDEBAR: RASTER DATA CATALOG FILTERS ---
    st.sidebar.header("Geophysical Data Catalog")
    
    # These will eventually be dynamically populated from the `usgs_surveys` Firestore collection
    surveys = [
        "Colorado Mineral Belt, Mid Block (2023)",
        "Colorado Mineral Belt, NE Block (2024)",
        "Sierra Madre / Medicine Bow Mountains"
    ]
    selected_survey = st.sidebar.selectbox("1. Select Earth MRI Survey", surveys)

    st.sidebar.subheader("Target Features")
    layer_types = {
        "Radiometric: Equivalent Thorium (eTh)": "Primary REE Proxy",
        "Radiometric: Equivalent Uranium (eU)": "Secondary Proxy",
        "Radiometric: Potassium (K)": "Background Geology",
        "Magnetic: Reduced-to-Pole (RTP)": "Physical Source Alignment",
        "Magnetic: First Vertical Derivative (1VD)": "Edge-Sharpening Filter"
    }
    
    selected_layer = st.sidebar.selectbox("2. Select Proxy Layer", list(layer_types.keys()))
    st.sidebar.caption(f"*Focus:* {layer_types[selected_layer]}")
    
    st.sidebar.divider()
    
    # --- ML PIPELINE CONTROLS (Future State) ---
    st.sidebar.header("Anomaly Detection (ML)")
    confidence_threshold = st.sidebar.slider("Model Confidence Threshold", 0.0, 1.0, 0.85)
    run_model = st.sidebar.button("Execute Detection Pipeline", type="primary", use_container_width=True)

    # --- MAIN CONTENT AREA ---
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.markdown(f"### Target View: {selected_survey}")
        st.caption(f"Currently viewing **{selected_layer}** payload data.")
        
        # --- MAP RENDERING ---
        # Centered roughly on the CO/WY border to accommodate all three surveys
        m = folium.Map(location=[40.5, -106.0], zoom_start=7, tiles='CartoDB positron')
        
        # TODO: Insert Cloud Optimized GeoTIFF (COG) rendering logic here.
        # This will likely utilize leafmap.foliumap or a rasterio bounds overlay 
        # based on the storage_uri retrieved from the `raster_assets` Firestore collection.

        st_folium(m, use_container_width=True)

    with col2:
        st.markdown("### Layer Metadata")
        st.info(
            "**Data Engineering Pipeline Status:**\n\n"
            "🟢 TIF Extracted\n"
            "🟢 Transformed to COG\n"
            "⚪ Uploaded to Cloud Storage\n"
            "⚪ Registered in Firestore"
        )
        
        st.markdown("### Identified Anomalies")
        if run_model:
            st.warning("ML Pipeline not yet connected. Configure the PyTorch/Scikit-Learn backend.")
        else:
            st.write("Awaiting model execution...")
            
        # Optional: Bring GenAI back here later to summarize the geological context 
        # of the specific Survey bounding box, rather than individual point mines.

if __name__ == "__main__":
    main()