import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Set the page config for the entire application
st.set_page_config(
    page_title="REEsource | Critical Mineral Intelligence", 
    page_icon="🌍", 
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    # --- HERO SECTION ---
    st.title("🌍 REEsource")
    st.subheader("Geophysical Anomaly Detection for Critical Minerals")
    st.divider()

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(
            """
            ### Project Overview
            The REEsource platform ingests, processes, and analyzes high-resolution airborne geophysical data 
            from the USGS Earth MRI initiative. By stacking magnetic and radiometric raster datasets, 
            this pipeline identifies statistical anomalies indicative of alkaline intrusions and carbonatites—the 
            primary geological hosts for Rare Earth Elements (REEs).

            **Current Target Regions:**
            * Colorado Mineral Belt (Mid & NE Blocks)
            * Sierra Madre / Medicine Bow Mountains

            ### Navigating the Platform
            Use the sidebar to explore the application:
            * **🌐 Geospatial Explorer:** View and filter the raw geophysical raster layers (Cloud Optimized GeoTIFFs) streamed directly from Google Cloud Storage.
            * **🧲 Anomaly Detection:** Execute the machine learning pipeline to identify target coordinate zones based on multi-feature thresholds (e.g., High Thorium, High Magnetics, Low Potassium).
            """
        )

    with col2:
        st.info(
            "**System Architecture**\n\n"
            "**Storage:** GCP Cloud Storage (Blob)\n"
            "**Metadata:** GCP Firestore (NoSQL)\n"
            "**Frontend:** Streamlit\n"
            "**Data Engineering:** Rasterio & GDAL\n"
        )
        
        st.markdown("---")
        st.caption(
            "Developed as a Master of Science in Data Analytics Capstone Project. "
            "Data provided by the U.S. Geological Survey (USGS)."
        )

if __name__ == "__main__":
    main()