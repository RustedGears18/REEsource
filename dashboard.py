import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
import urllib.parse
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
else:
    st.sidebar.title("REEsource")
st.sidebar.divider()

def generate_healing_link(row):
    official_link = row.get('source_link')
    if pd.notna(official_link) and str(official_link).startswith('http'):
        return official_link
    lat, lon = row.get('latitude'), row.get('longitude')
    if pd.notna(lat) and pd.notna(lon):
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    deposit = str(row.get('deposit_name', '')).replace('_', ' ')
    state = str(row.get('state', ''))
    return f"https://www.google.com/search?q={urllib.parse.quote(f'{deposit} mine {state}')}"

@st.cache_data(ttl=3600)
def fetch_firestore_data(collection_name='mrds_feedstock_profiles'):
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            db = firestore.Client.from_service_account_info(creds_dict)
        else:
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            db = firestore.Client.from_service_account_json(key_path) if key_path else firestore.Client()
            
        docs = db.collection(collection_name).stream()
        data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'location' in doc_dict and doc_dict['location']:
                doc_dict['latitude'] = doc_dict['location'].get('latitude')
                doc_dict['longitude'] = doc_dict['location'].get('longitude')
            data.append(doc_dict)
        
        return pd.DataFrame(data).dropna(subset=['latitude', 'longitude']) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"Firestore Query Error: {e}")
        return pd.DataFrame()

def get_mrds_symbology(status):
    """Maps operational status to MRDS shape standards (sides, rotation)."""
    status = str(status).lower()
    if 'producer' in status:
        return 4, 45  # Square (rotated to sit flat)
    elif 'plant' in status:
        return 3, 0   # Triangle (points up)
    else:
        return 30, 0  # Circle (Prospect / Occurrence)

def main():
    st.title("REEsource: MRDS Feedstock Intelligence")
    st.markdown("### *Unearthing tomorrow's critical mineral supply*")
    
    # Glossary & Definitions Callout
    st.info(
        "**Critical Mineral:** A non-fuel mineral or mineral material essential to the economic and "
        "national security of the United States, the supply chain of which is vulnerable to disruption.\n\n"
        "**Rare Earth Element (REE):** A set of 17 chemically similar metallic elements (the 15 lanthanides "
        "plus scandium and yttrium), critical for high-tech, defense, and advanced metallurgical applications."
    )

    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    df['reference_link'] = df.apply(generate_healing_link, axis=1)
    filtered_df = df.copy()

    # --- SIDEBAR SEARCH & FILTERS ---
    st.sidebar.header("Search")
    search_list = ['None'] + sorted(filtered_df['deposit_name'].dropna().unique().tolist())
    target_deposit = st.sidebar.selectbox("Find Specific Deposit...", search_list)
    
    st.sidebar.header("Location Filters")
    available_states = ['All US'] + sorted([s for s in filtered_df['state'].dropna().unique().tolist() if s not in ['None', 'UNKNOWN']])
    selected_state = st.sidebar.selectbox("Select State", available_states)

    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    st.sidebar.header("Operational Filters")
    categories = ['All'] + sorted(filtered_df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Viability / Development Status", categories)

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]

    st.sidebar.metric(label="Visible Targets", value=len(filtered_df))

    # --- DYNAMIC ZOOM LOGIC ---
    # Zoom level 12 roughly equals a 10-mile overhead frame
    if target_deposit != 'None':
        target_row = df[df['deposit_name'] == target_deposit].iloc[0]
        map_center = [target_row['latitude'], target_row['longitude']]
        zoom_level = 12
    elif not filtered_df.empty:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 6 if selected_state != 'All US' else 4
    else:
        map_center = [39.8283, -98.5795]
        zoom_level = 4

    # --- MAP RENDERING (Multi-Layer) ---
    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles=None)

    # 1. Default Layer: Esri Satellite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite (Default)',
        control=True
    ).add_to(m)
    # 2. Toggle Layer: CartoDB Positron
    folium.TileLayer('CartoDB positron', name='Light Basemap', control=True).add_to(m)
    # 3. Toggle Layer: OpenStreetMap
    folium.TileLayer('OpenStreetMap', name='Street Map', control=True).add_to(m)
    
    # Allow user to switch between the registered layers
    folium.LayerControl().add_to(m)

    # Add shapes based on MRDS standards
    for _, row in filtered_df.iterrows():
        sides, rot = get_mrds_symbology(row.get('operational_category'))
        summary = row.get('feedstock_summary', 'No summary available.')
        
        tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                       f"State: {row.get('state', 'Unknown')}<br>" \
                       f"Status: {row.get('operational_category', 'Unknown')}<br><br>" \
                       f"<i>{summary}</i>"
                       
        folium.RegularPolygonMarker(
            location=[row['latitude'], row['longitude']],
            number_of_sides=sides,
            rotation=rot,
            radius=7 if sides < 30 else 5, # Make squares/triangles slightly larger for visibility
            popup=folium.Popup(tooltip_text, max_width=350),
            tooltip=row.get('deposit_name', 'Unknown'),
            color="#3186cc",
            fill=True,
            fill_color="#3186cc",
            fill_opacity=0.7
        ).add_to(m)

    # --- UI LAYOUT & TABLES ---
    st_data = st_folium(m, width=1200, height=500, returned_objects=["last_object_clicked_tooltip"])
        
    st.subheader("Extracted Site Specifications")
    st.dataframe(
        filtered_df[[
            'deposit_name', 'production_size', 'operational_category', 
            'cm_present', 'ree_present', 'disc_yr', 'yr_fst_prd', 'ref', 'reference_link'
        ]],
        column_config={
            "deposit_name": "Deposit",
            "production_size": "Size",
            "operational_category": "Status",
            "cm_present": "Critical Minerals (Viable)",
            "ree_present": "REEs (Viable)",
            "disc_yr": "Disc. Year",
            "yr_fst_prd": "1st Prod. Year",
            "ref": "USGS Reference(s)",
            "reference_link": st.column_config.LinkColumn(
                "Source / Location", 
                display_text=r"^(?:https?:\/\/(?:www\.)?)?(.{0,30})" 
            )
        },
        hide_index=True,
        use_container_width=True
    )

    # Contextual Summary Output via Map Click
    if st_data and st_data.get('last_object_clicked_tooltip'):
        selected_deposit = st_data['last_object_clicked_tooltip']
        selected_row = filtered_df[filtered_df['deposit_name'] == selected_deposit]
        if not selected_row.empty:
            st.info(f"**{selected_deposit} Profile:**\n\n" + selected_row.iloc[0]['feedstock_summary'])

if __name__ == "__main__":
    main()