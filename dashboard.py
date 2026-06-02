import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
from dotenv import load_dotenv

load_dotenv()

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

# Set of standard REE abbreviations and common USGS tags
REE_KEYWORDS = {
    'REE', 'RARE EARTH', 'SC', 'Y', 'LA', 'CE', 'PR', 'ND', 
    'SM', 'EU', 'GD', 'TB', 'DY', 'HO', 'ER', 'TM', 'YB', 'LU'
}

def is_ree(commodities_list):
    if not isinstance(commodities_list, list):
        return False
    upper_comms = [str(c).upper().strip() for c in commodities_list]
    return any(item in REE_KEYWORDS for item in upper_comms)

def generate_healing_link(row):
    official_link = row.get('source_link')
    if pd.notna(official_link) and str(official_link).startswith('http'):
        return official_link
    clean_name = str(row.get('deposit_name', '')).replace(' ', '+')
    state = str(row.get('state', ''))
    return f"https://www.mindat.org/search.php?search={clean_name}+{state}"

@st.cache_data(ttl=3600)
def fetch_firestore_data(collection_name='usmin_critical_minerals'):
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
            
            # Ensure fallback if origin wasn't explicitly set in early database versions
            doc_dict['feedstock_origin'] = doc_dict.get('feedstock_origin', 'Primary Geologic')
                
            data.append(doc_dict)
            
        if not data:
            return pd.DataFrame()
            
        return pd.DataFrame(data).dropna(subset=['latitude', 'longitude'])
        
    except Exception as e:
        st.error(f"Firestore Query Error: {e}")
        return pd.DataFrame()

def get_marker_color(origin_type):
    """Assigns distinct colors to visually separate ore vs. waste."""
    if origin_type == "Primary Geologic":
        return "#3186cc" # Blue
    elif origin_type == "Secondary Mine Waste":
        return "#2ecc71" # Green
    elif origin_type == "Coal Byproducts":
        return "#ff7800" # Orange
    return "#95a5a6" # Gray fallback

def main():
    st.title("REEsource: Feedstock Intelligence")
    st.markdown("Interactive geospatial mapping of Rare Earth Element (REE) and critical mineral deposits across the United States.")

    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    df['reference_link'] = df.apply(generate_healing_link, axis=1)

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Commodity Focus")
    target_focus = st.sidebar.radio("Select Resource Type", ["Rare Earth Elements (REEs)", "All Critical Minerals"], index=0)

    filtered_df = df.copy()
    if target_focus == "Rare Earth Elements (REEs)":
        filtered_df = filtered_df[filtered_df['primary_commodities'].apply(is_ree)]

    st.sidebar.header("Feedstock Classification")
    available_origins = sorted([o for o in filtered_df['feedstock_origin'].dropna().unique().tolist()])
    selected_origins = st.sidebar.multiselect(
        "Select Source Origin", 
        options=available_origins, 
        default=available_origins
    )
    if selected_origins:
        filtered_df = filtered_df[filtered_df['feedstock_origin'].isin(selected_origins)]

    st.sidebar.header("Location Filters")
    available_states = ['All US'] + sorted([s for s in filtered_df['state'].dropna().unique().tolist() if s != 'None'])
    selected_state = st.sidebar.selectbox("Select State", available_states)

    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    st.sidebar.metric(label="Target Feedstock Sites", value=len(filtered_df))

    # --- MAP RENDERING ---
    if not filtered_df.empty:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 6 if selected_state != 'All US' else 4
    else:
        map_center = [39.8283, -98.5795]
        zoom_level = 4

    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles="CartoDB positron")

    for _, row in filtered_df.iterrows():
        origin = row.get('feedstock_origin', 'Unknown')
        marker_color = get_marker_color(origin)
        
        tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                       f"Classification: {origin}<br>" \
                       f"State: {row.get('state', 'Unknown')}<br>" \
                       f"Commodities: {row.get('commodities_str', '')}"
                       
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=6,
            popup=folium.Popup(tooltip_text, max_width=300),
            tooltip=row.get('deposit_name', 'Unknown'),
            color=marker_color,
            fill=True,
            fill_color=marker_color
        ).add_to(m)

    # --- UI LAYOUT ---
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st_data = st_folium(m, width=700, height=500)
        
    with col2:
        st.subheader("Site Details")
        st.dataframe(
            filtered_df[['deposit_name', 'state', 'feedstock_origin', 'reference_link']],
            column_config={
                "deposit_name": "Deposit",
                "state": "State",
                "feedstock_origin": "Origin",
                "reference_link": st.column_config.LinkColumn(
                    "Source", 
                    display_text=r"^(?:https?:\/\/(?:www\.)?)?(.{0,40})" 
                )
            },
            hide_index=True,
            use_container_width=True
        )

if __name__ == "__main__":
    main()