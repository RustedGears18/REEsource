import os
import json
import urllib.parse
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
from google.oauth2 import service_account
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

# --- DATABASE CONNECTION ---
@st.cache_resource
def get_db_client():
    if "gcp_service_account" in st.secrets:
        key_dict = json.loads(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=creds.project_id)
    else:
        return firestore.Client()

def generate_healing_link(row):
    official_link = row.get('source_link')
    if pd.notna(official_link) and str(official_link).startswith('http'):
        return official_link
    
    lat = row.get('latitude')
    lon = row.get('longitude')
    if pd.notna(lat) and pd.notna(lon):
        return f"http://googleusercontent.com/maps.google.com/{lat},{lon}"
    return "#"

# --- DATA FETCHING ---
@st.cache_data(ttl=600)
def fetch_data():
    db = get_db_client()
    docs = db.collection("usmin_critical_minerals").stream()
    data = []
    
    for doc in docs:
        d = doc.to_dict()
        d['doc_id'] = doc.id
        d['executive_summary'] = d.get('executive_summary', None)
        
        # --- BULLETPROOF COORDINATE HUNTER ---
        lat = None
        lon = None
        
        # 1. Search root level for any variation (case-insensitive)
        for key, val in d.items():
            k_lower = key.lower()
            if k_lower in ['latitude', 'lat', 'lat_wgs84', 'y']:
                lat = val
            elif k_lower in ['longitude', 'lon', 'long', 'long_wgs84', 'x']:
                lon = val
                
        # 2. Check nested 'location' dictionary
        if 'location' in d and isinstance(d['location'], dict):
            lat = d['location'].get('latitude', lat)
            lon = d['location'].get('longitude', lon)
            
        # 3. Check for native Firestore GeoPoint objects
        if 'location' in d and hasattr(d['location'], 'latitude'):
            lat = d['location'].latitude
            lon = d['location'].longitude
            
        # Assign discovered coordinates
        d['latitude_extracted'] = lat
        d['longitude_extracted'] = lon
        
        data.append(d)
        
    df = pd.DataFrame(data)
    
    if df.empty:
        return pd.DataFrame(columns=['doc_id', 'latitude', 'longitude', 'state', 'feedstock_origin', 'deposit_name'])
        
    # Convert safely to numeric, forcing text/invalid data to NaN
    df['latitude'] = pd.to_numeric(df['latitude_extracted'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude_extracted'], errors='coerce')
    
    return df

def fetch_sources(doc_id):
    db = get_db_client()
    sources_ref = db.collection("usmin_critical_minerals").document(doc_id).collection("unstructured_assets").stream()
    return [s.to_dict() for s in sources_ref]

def get_marker_color(origin):
    if origin == 'Primary Geologic':
        return 'blue'
    elif origin == 'Secondary Mine Waste':
        return 'orange'
    return 'gray'

# --- MAIN APP LOGIC ---
df = fetch_data()
df['reference_link'] = df.apply(generate_healing_link, axis=1)

st.title("U.S. Critical Minerals & Rare Earths")

# --- SIDEBAR FILTERS ---
st.sidebar.subheader("Filter Data")
states = sorted(df['state'].dropna().unique().tolist()) if 'state' in df.columns else []
selected_state = st.sidebar.selectbox("Select State", ["All"] + states)

origins = sorted(df['feedstock_origin'].dropna().unique().tolist()) if 'feedstock_origin' in df.columns else []
selected_origin = st.sidebar.selectbox("Feedstock Origin", ["All"] + origins)

filtered_df = df.copy()
if selected_state != "All":
    filtered_df = filtered_df[filtered_df['state'] == selected_state]
if selected_origin != "All":
    filtered_df = filtered_df[filtered_df['feedstock_origin'] == selected_origin]

# --- BUILD FOLIUM MAP ---
map_df = filtered_df.dropna(subset=['latitude', 'longitude'])

# 🚨 THE DEBUGGER: If map is empty but data exists, tell us why!
if map_df.empty and not filtered_df.empty:
    st.error("🚨 Map Data Error: We found records, but none of them have valid numeric coordinates!")
    st.write("Here is the exact raw data Python is seeing for the first record. Look closely at the keys and values to see where the coordinates are hiding (or if the cache is stale):")
    st.json(filtered_df.iloc[0].to_dict())

map_center = [39.8283, -98.5795] 
if not map_df.empty:
    map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]

m = folium.Map(location=map_center, zoom_start=4, tiles="CartoDB positron")

for _, row in map_df.iterrows():
    origin = row.get('feedstock_origin', 'Unknown')
    marker_color = get_marker_color(origin)
    
    tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                   f"Classification: {origin}<br>" \
                   f"State: {row.get('state', 'Unknown')}<br>"
                   
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
    st_data = st_folium(m, width=700, height=600, returned_objects=["last_object_clicked"])
    
with col2:
    st.subheader("Site Details")
    if st_data and st_data.get("last_object_clicked"):
        lat = st_data["last_object_clicked"]["lat"]
        lon = st_data["last_object_clicked"]["lng"]
        
        match = filtered_df[
            (filtered_df['latitude'].round(4) == round(lat, 4)) & 
            (filtered_df['longitude'].round(4) == round(lon, 4))
        ]
        
        if not match.empty:
            site = match.iloc[0]
            st.markdown(f"### {site.get('deposit_name', 'Unknown Deposit')}")
            st.caption(f"**Origin:** {site.get('feedstock_origin', 'Unknown Origin')} | **State:** {site.get('state', '')}")
            st.divider()
            
            st.markdown("#### Executive Summary")
            if pd.notna(site.get('executive_summary')) and site.get('executive_summary'):
                st.info(site['executive_summary'])
            else:
                st.warning("No summary available yet. Run backend harvester to generate.")
            
            st.markdown("#### Discovered Sources")
            sources = fetch_sources(site['doc_id'])
            if sources:
                for s in sources:
                    title = s.get('title', 'Target Link')
                    url = s.get('source_url', '#')
                    st.markdown(f"- [{title}]({url})")
            else:
                st.write("No external sources harvested yet.")
        else:
            st.write("Details could not be resolved. Please try another pin.")
    else:
        st.write("Click a map pin to load the AI-generated profile and source links.")
        st.write("---")
        st.dataframe(
            filtered_df[['deposit_name', 'state', 'feedstock_origin', 'reference_link']],
            column_config={
                "deposit_name": "Deposit",
                "state": "State",
                "feedstock_origin": "Origin",
                "reference_link": st.column_config.LinkColumn("Source / Location")
            },
            hide_index=True,
            use_container_width=True
        )