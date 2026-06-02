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

# Load GCP credentials (Fallback for local development)
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
    """
    Returns an authenticated Firestore client.
    Prefers Streamlit Secrets (Cloud) but falls back to .env (Local).
    """
    if "gcp_service_account" in st.secrets:
        # Cloud Deployment: Parse literal JSON string from Secrets
        key_dict = json.loads(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=creds.project_id)
    else:
        # Local Development: Relies on GOOGLE_APPLICATION_CREDENTIALS in .env
        return firestore.Client()

def generate_healing_link(row):
    """
    Returns the official USGS link if available. 
    Otherwise, utilizes the exact coordinates to drop a Google Maps pin.
    """
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
        data.append(d)
        
    df = pd.DataFrame(data)
    
    # 1. If the database is completely empty, return an empty DF with the right columns
    if df.empty:
        return pd.DataFrame(columns=['doc_id', 'latitude', 'longitude', 'state', 'feedstock_origin', 'deposit_name'])
        
    # 2. If the data exists, but the lat/lon columns are missing entirely, add them safely
    if 'latitude' not in df.columns:
        df['latitude'] = pd.NA
    if 'longitude' not in df.columns:
        df['longitude'] = pd.NA
        
    # 3. Force them to be numeric (turns weird strings/nulls into NaN) and drop invalid rows
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df = df.dropna(subset=['latitude', 'longitude'])
    
    return df

def fetch_sources(doc_id):
    """Dynamically fetches harvested URIs for a specific record."""
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

# Apply reference links
df['reference_link'] = df.apply(generate_healing_link, axis=1)

st.title("U.S. Critical Minerals & Rare Earths")

# --- SIDEBAR FILTERS ---
st.sidebar.subheader("Filter Data")

states = sorted(df['state'].dropna().unique().tolist())
selected_state = st.sidebar.selectbox("Select State", ["All"] + states)

origins = sorted(df['feedstock_origin'].dropna().unique().tolist())
selected_origin = st.sidebar.selectbox("Feedstock Origin", ["All"] + origins)

filtered_df = df.copy()
if selected_state != "All":
    filtered_df = filtered_df[filtered_df['state'] == selected_state]
if selected_origin != "All":
    filtered_df = filtered_df[filtered_df['feedstock_origin'] == selected_origin]

# --- BUILD FOLIUM MAP ---
map_center = [39.8283, -98.5795] # Center of US
if not filtered_df.empty:
    map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]

m = folium.Map(location=map_center, zoom_start=4, tiles="CartoDB positron")

for _, row in filtered_df.iterrows():
    origin = row.get('feedstock_origin', 'Unknown')
    marker_color = get_marker_color(origin)
    
    tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                   f"Classification: {origin}<br>" \
                   f"State: {row.get('state', 'Unknown')}<br>" \
                   f"Legacy Commodities: {row.get('commodities_str', '')}"
                   
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
    # Render map and return clicked object data
    st_data = st_folium(m, width=700, height=600, returned_objects=["last_object_clicked"])
    
with col2:
    st.subheader("Site Details")
    
    # 1. Check if a pin was clicked
    if st_data and st_data.get("last_object_clicked"):
        lat = st_data["last_object_clicked"]["lat"]
        lon = st_data["last_object_clicked"]["lng"]
        
        # 2. Find matching record (using a small float tolerance rounding just in case)
        match = filtered_df[
            (filtered_df['latitude'].round(4) == round(lat, 4)) & 
            (filtered_df['longitude'].round(4) == round(lon, 4))
        ]
        
        if not match.empty:
            site = match.iloc[0]
            
            # --- Dynamic Profile Render ---
            st.markdown(f"### {site.get('deposit_name', 'Unknown Deposit')}")
            st.caption(f"**Origin:** {site.get('feedstock_origin', 'Unknown Origin')} | **State:** {site.get('state', '')}")
            
            st.divider()
            
            # AI Executive Summary
            st.markdown("#### Executive Summary")
            if pd.notna(site.get('executive_summary')) and site.get('executive_summary'):
                st.info(site['executive_summary'])
            else:
                st.warning("No summary available yet. Run backend harvester to generate.")
            
            # Subcollection Query for Sources
            st.markdown("#### Discovered Sources")
            sources = fetch_sources(site['doc_id'])
            
            if sources:
                for s in sources:
                    title = s.get('title', 'Target Link')
                    url = s.get('source_url', '#')
                    # Streamlit Markdown Bullet List
                    st.markdown(f"- [{title}]({url})")
            else:
                st.write("No external sources harvested yet.")
                
        else:
            st.write("Details could not be resolved. Please try another pin.")
            
    else:
        # 3. Default State (Before any pin is clicked)
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