import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
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
logo_path = os.path.join("assets", "REEsource brand dark.png")

if os.path.exists(logo_path):
    st.sidebar.image(logo_path, use_container_width=True)
    st.sidebar.divider()
else:
    st.sidebar.title("REEsource")
    st.sidebar.divider()
# -------------------------

@st.cache_data(ttl=3600)
def fetch_firestore_data(collection_name='usmin_critical_minerals'):
    """Pulls all parent documents from the specified Firestore collection."""
    
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            db = firestore.Client.from_service_account_info(creds_dict)
        else:
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if key_path:
                db = firestore.Client.from_service_account_json(key_path)
            else:
                db = firestore.Client()
    except Exception as auth_err:
        st.error(f"Authentication Setup Failed: {auth_err}")
        return pd.DataFrame()

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
    st.title("REEsource: Critical Mineral Feedstocks")
    st.markdown("Interactive geospatial mapping of critical mineral deposits across the United States.")

    # 1. Fetch Data
    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    # 2. Build Sidebar Filters
    st.sidebar.header("Location Filters")
    
    # State Selection
    available_states = ['All US'] + sorted([s for s in df['state'].dropna().unique().tolist() if s != 'None'])
    selected_state = st.sidebar.selectbox("Select State", available_states)

    filtered_df = df.copy()
    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    st.sidebar.header("Feedstock Filters")
    
    # Operational Category Selection
    categories = ['All'] + sorted(filtered_df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Operational Category", categories)

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]
        
    st.sidebar.metric(label="Visible Feedstock Sites", value=len(filtered_df))

    # 3. Dynamic Map Centering
    if not filtered_df.empty:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 6 if selected_state != 'All US' else 4
    else:
        # Default view of the continental US if filters yield no results
        map_center = [39.8283, -98.5795]
        zoom_level = 4

    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles="CartoDB positron")

    for _, row in filtered_df.iterrows():
        tooltip_text = f"<b>{row['deposit_name']}</b><br>" \
                       f"State: {row.get('state', 'Unknown')}<br>" \
                       f"Type: {row['geology'].get('deposit_type', 'Unknown')}<br>" \
                       f"Commodities: {row.get('commodities_str', '')}"
                       
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
            filtered_df[['deposit_name', 'state', 'operational_category', 'commodities_str']],
            hide_index=True,
            use_container_width=True
        )

if __name__ == "__main__":
    main()