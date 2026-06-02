import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
import urllib.parse
from dotenv import load_dotenv

# Load GCP credentials
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

def generate_healing_link(row):
    """Provides a self-healing reference link to USGS MRDS or Google Maps."""
    official_link = row.get('source_link')
    if pd.notna(official_link) and str(official_link).startswith('http'):
        return official_link
    
    lat = row.get('latitude')
    lon = row.get('longitude')
    
    if pd.notna(lat) and pd.notna(lon):
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        
    deposit = str(row.get('deposit_name', '')).replace('_', ' ')
    state = str(row.get('state', ''))
    query = urllib.parse.quote(f"{deposit} mine {state}")
    return f"https://www.google.com/search?q={query}"

@st.cache_data(ttl=3600)
def fetch_firestore_data(collection_name='mrds_feedstock_profiles'):
    """Fetches our newly structured MRDS data from Firestore"""
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
            
        return pd.DataFrame(data).dropna(subset=['latitude', 'longitude'])
        
    except Exception as e:
        st.error(f"Firestore Query Error: {e}")
        return pd.DataFrame()

def main():
    st.title("REEsource: MRDS Feedstock Intelligence")
    st.markdown("Interactive geospatial mapping of Grade A critical mineral and REE feedstocks based on USGS MRDS evaluations.")

    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    df['reference_link'] = df.apply(generate_healing_link, axis=1)

    # --- SIDEBAR FILTERS ---
    filtered_df = df.copy()

    st.sidebar.header("Location Filters")
    available_states = ['All US'] + sorted([s for s in filtered_df['state'].dropna().unique().tolist() if s != 'None' and s != 'UNKNOWN'])
    selected_state = st.sidebar.selectbox("Select State", available_states)

    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    st.sidebar.header("Operational Filters")
    categories = ['All'] + sorted(filtered_df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Viability / Development Status", categories)

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]
        
    # Added a filter explicitly for the 'prod_size'
    sizes = ['All'] + sorted(filtered_df['production_size'].dropna().unique().tolist())
    selected_size = st.sidebar.selectbox("Production Size", sizes)
    if selected_size != 'All':
        filtered_df = filtered_df[filtered_df['production_size'] == selected_size]

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
        # Injecting the newly created feedstock_summary directly into the map popup!
        summary = row.get('feedstock_summary', 'No summary available.')
        
        tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                       f"State: {row.get('state', 'Unknown')}<br>" \
                       f"Status: {row.get('operational_category', 'Unknown')}<br><br>" \
                       f"<i>{summary}</i>"
                       
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=6,
            popup=folium.Popup(tooltip_text, max_width=350),
            tooltip=row.get('deposit_name', 'Unknown'),
            color="#3186cc",
            fill=True,
            fill_color="#3186cc"
        ).add_to(m)

    # --- UI LAYOUT ---
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Return state needed to capture map clicks
        st_data = st_folium(m, width=700, height=500, returned_objects=["last_object_clicked_tooltip"])
        
    with col2:
        st.subheader("Site Details")
        st.dataframe(
            filtered_df[['deposit_name', 'state', 'operational_category', 'reference_link']],
            column_config={
                "deposit_name": "Deposit",
                "state": "State",
                "operational_category": "Status",
                "reference_link": st.column_config.LinkColumn(
                    "Source / Location", 
                    display_text=r"^(?:https?:\/\/(?:www\.)?)?(.{0,40})" 
                )
            },
            hide_index=True,
            use_container_width=True
        )

        st.subheader("Feedstock Profile Summary")
        # Dynamic Streamlit logic: When a user clicks a pin on the map, it renders the summary here
        if st_data and st_data.get('last_object_clicked_tooltip'):
            selected_deposit = st_data['last_object_clicked_tooltip']
            selected_row = filtered_df[filtered_df['deposit_name'] == selected_deposit]
            if not selected_row.empty:
                st.write(f"**{selected_deposit}**")
                st.info(selected_row.iloc[0]['feedstock_summary'])
        else:
            st.write("Click a map marker to view its viability summary.")

if __name__ == "__main__":
    main()