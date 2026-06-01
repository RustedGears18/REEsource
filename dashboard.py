import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json # Add this import to the top of your file
from dotenv import load_dotenv

# Load GCP credentials from your secure .env file
load_dotenv()

# Streamlit Page Configuration MUST be the first Streamlit command
st.set_page_config(
    page_title="REEsource Geospatial Dashboard",
    page_icon="🌍",
    layout="wide"
)

# --- BRANDING & ASSETS ---
# Check if the asset exists to prevent application crashes if the path changes
logo_path = os.path.join("assets", "REEsource brand dark.png")

if os.path.exists(logo_path):
    # Places the logo cleanly at the top of the navigation sidebar
    st.sidebar.image(logo_path, use_container_width=True)
    st.sidebar.divider()
else:
    # Fallback text if the image is moved or renamed
    st.sidebar.title("REEsource")
    st.sidebar.divider()
# -------------------------

@st.cache_data(ttl=3600)
def fetch_firestore_data(collection_name='colorado_critical_minerals'):
    """Pulls all parent documents from the specified Firestore collection."""
    
    # 1. Hybrid Authentication Block
    try:
        if "gcp_service_account" in st.secrets:
            # Running Live on Streamlit Cloud: Parse credentials from secure UI secrets
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            db = firestore.Client.from_service_account_info(creds_dict)
        else:
            # Running Locally: Explicitly pass the path from your local .env file
            # Make sure your .env has: GOOGLE_APPLICATION_CREDENTIALS="path/to/your/key.json"
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if key_path:
                db = firestore.Client.from_service_account_json(key_path)
            else:
                # Fallback to default discovery if path isn't explicit
                db = firestore.Client()
    except Exception as auth_err:
        st.error(f"Authentication Setup Failed: {auth_err}")
        return pd.DataFrame()

    # 2. Data Streaming Block (Remains the same)
    try:
        collection_ref = db.collection(collection_name)
        docs = collection_ref.stream()
        
        data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'location' in doc_dict and doc_dict['location']:
                doc_dict['latitude'] = doc_dict['location'].get('latitude')
                doc_dict['longitude'] = doc_dict['location'].get('longitude')
                
            if 'primary_commodities' in doc_dict:
                doc_dict['commodities_str'] = ", ".join(doc_dict['primary_commodities'])
                
            data.append(doc_dict)
            
        if not data:
            return pd.DataFrame()
            
        df = pd.DataFrame(data)
        return df.dropna(subset=['latitude', 'longitude'])
        
    except Exception as e:
        st.error(f"Firestore Query Error: {e}")
        return pd.DataFrame()

def main():
    st.title("REEsource 2026: Colorado Critical Mineral Feedstocks")
    st.markdown("Interactive geospatial mapping of potential FJH Carbochlorination inputs.")

    # 1. Fetch Data
    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    # 2. Build Sidebar Filters
    st.sidebar.header("Feedstock Filters")
    
    categories = ['All'] + sorted(df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Operational Category", categories)

    filtered_df = df.copy()
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]
        
    st.sidebar.metric(label="Visible Feedstock Sites", value=len(filtered_df))

    # 3. Build the Map
    map_center = [39.0598, -105.3111]
    m = folium.Map(location=map_center, zoom_start=7, tiles="CartoDB positron")

    for _, row in filtered_df.iterrows():
        tooltip_text = f"<b>{row['deposit_name']}</b><br>" \
                       f"Type: {row['geology'].get('deposit_type', 'Unknown')}<br>" \
                       f"Commodities: {row['commodities_str']}"
                       
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=6,
            popup=folium.Popup(tooltip_text, max_width=300),
            tooltip=row['deposit_name'],
            color="#3186cc",
            fill=True,
            fill_color="#3186cc"
        ).add_to(m)

    # 4. Render Map and Data Table side-by-side
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st_data = st_folium(m, width=700, height=500)
        
    with col2:
        st.subheader("Site Details")
        st.dataframe(
            filtered_df[['deposit_name', 'operational_category', 'commodities_str']],
            hide_index=True,
            use_container_width=True
        )

if __name__ == "__main__":
    main()