import os
import json
import tempfile
import urllib.parse
from datetime import datetime, timezone
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
from google.oauth2 import service_account
from google import genai
from dotenv import load_dotenv

# Load GCP credentials (local fallback)
load_dotenv()

st.set_page_config(
    page_title="REEsource Geospatial Dashboard",
    page_icon="🌍",
    layout="wide"
)

# --- GCP CREDENTIAL HANDLING FOR STREAMLIT CLOUD (VERTEX AI) ---
# The GenAI SDK requires a physical file path for Application Default Credentials.
# If we are in Streamlit Cloud, we safely write the secret to a temporary file.
if "gcp_service_account" in st.secrets:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        f.write(st.secrets["gcp_service_account"])
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name

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
        
        # Capture the AI generation timestamp
        d['summary_generated_at'] = d.get('summary_generated_at', None)
        
        lat = None
        lon = None
        
        for key, val in d.items():
            k_lower = key.lower()
            if k_lower in ['latitude', 'lat', 'lat_wgs84', 'y']:
                lat = val
            elif k_lower in ['longitude', 'lon', 'long', 'long_wgs84', 'x']:
                lon = val
                
        if 'location' in d and isinstance(d['location'], dict):
            lat = d['location'].get('latitude', lat)
            lon = d['location'].get('longitude', lon)
            
        if 'location' in d and hasattr(d['location'], 'latitude'):
            lat = d['location'].latitude
            lon = d['location'].longitude
            
        d['latitude_extracted'] = lat
        d['longitude_extracted'] = lon
        data.append(d)
        
    df = pd.DataFrame(data)
    
    if df.empty:
        return pd.DataFrame(columns=['doc_id', 'latitude', 'longitude', 'state', 'feedstock_origin', 'deposit_name', 'summary_generated_at'])
        
    df['latitude'] = pd.to_numeric(df['latitude_extracted'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude_extracted'], errors='coerce')
    return df

def fetch_sources(doc_id):
    db = get_db_client()
    sources_ref = db.collection("usmin_critical_minerals").document(doc_id).collection("unstructured_assets").stream()
    return [s.to_dict() for s in sources_ref]

# --- ON-DEMAND AI HARVESTER ---
def run_live_harvester(doc_id, deposit_name, state, feedstock_origin):
    """Triggers Gemini via Vertex AI to research a site and write it to Firestore."""
    db = get_db_client()
    gcp_project = db.project
    
    ai_client = genai.Client(vertexai=True, project=gcp_project, location="us-central1")
    
    prompt = (
        f"Act as a critical minerals research assistant. Tell me about the '{deposit_name}' "
        f"located in {state}. It is classified as '{feedstock_origin}'. \n\n"
        f"1. Provide a concise executive summary (~150 words) detailing its geological context, "
        f"historical operations, and potential as a U.S. critical mineral feedstock. \n"
        f"2. Add a **Recent Developments** section. Search the web and explicitly list up to 3 "
        f"recent news items, policy changes, or operational updates regarding this site or its immediate region. \n\n"
        f"Include high-quality sources."
    )
    
    response = ai_client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}], 
            temperature=0.2
        )
    )
    
    doc_ref = db.collection("usmin_critical_minerals").document(doc_id)
    
    doc_ref.update({
        "executive_summary": response.text,
        "summary_generated_at": firestore.SERVER_TIMESTAMP
    })
    
    if response.candidates and response.candidates[0].grounding_metadata:
        metadata = response.candidates[0].grounding_metadata
        if metadata.grounding_chunks:
            sub_collection_ref = doc_ref.collection("unstructured_assets")
            
            for index, chunk in enumerate(metadata.grounding_chunks):
                if chunk.web:
                    asset_id = f"web_source_{index}"
                    sub_collection_ref.document(asset_id).set({
                        "asset_type": "discovered_web_target",
                        "source_url": chunk.web.uri,
                        "title": chunk.web.title,
                        "harvest_status": "pending_harvest",
                        "discovered_at": firestore.SERVER_TIMESTAMP
                    }, merge=True)

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

# --- SIDEBAR FILTERS & SEARCH ---
st.sidebar.subheader("🔍 Search & Filter")

search_query = st.sidebar.text_input("Search by Deposit Name (e.g., 'Alma')", "")

states = sorted(df['state'].dropna().unique().tolist()) if 'state' in df.columns else []
selected_state = st.sidebar.selectbox("Select State", ["All"] + states)

origins = sorted(df['feedstock_origin'].dropna().unique().tolist()) if 'feedstock_origin' in df.columns else []
selected_origin = st.sidebar.selectbox("Feedstock Origin", ["All"] + origins)

filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['deposit_name'].str.contains(search_query, case=False, na=False)]
if selected_state != "All":
    filtered_df = filtered_df[filtered_df['state'] == selected_state]
if selected_origin != "All":
    filtered_df = filtered_df[filtered_df['feedstock_origin'] == selected_origin]

# --- BUILD FOLIUM MAP ---
map_df = filtered_df.dropna(subset=['latitude', 'longitude'])

zoom_level = 4
map_center = [39.8283, -98.5795] 

if not map_df.empty:
    if len(map_df) == 1:
        map_center = [map_df['latitude'].iloc[0], map_df['longitude'].iloc[0]]
        zoom_level = 12 
    else:
        map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
        zoom_level = 4 

m = folium.Map(location=map_center, zoom_start=zoom_level)

folium.TileLayer('CartoDB positron', name='Clean Light Map').add_to(m)

folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Satellite Terrain',
    max_zoom=18
).add_to(m)

folium.TileLayer(
    tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attr='OpenTopoMap',
    name='Topographic Zones',
    max_zoom=17
).add_to(m)

folium.LayerControl().add_to(m)

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

# --- UI LAYOUT: FULL WIDTH MAP ---
st_data = st_folium(m, use_container_width=True, height=550, returned_objects=["last_object_clicked"])

st.divider()

# --- UI LAYOUT: BOTTOM DETAILS SECTION ---
st.header("Site Details & AI Profile")

if st_data and st_data.get("last_object_clicked"):
    lat = st_data["last_object_clicked"]["lat"]
    lon = st_data["last_object_clicked"]["lng"]
    
    match = filtered_df[
        (filtered_df['latitude'].round(4) == round(lat, 4)) & 
        (filtered_df['longitude'].round(4) == round(lon, 4))
    ]
    
    if not match.empty:
        site = match.iloc[0]
        
        st.subheader(f"📍 {site.get('deposit_name', 'Unknown Deposit')}")
        st.caption(f"**Classification:** {site.get('feedstock_origin', 'Unknown Origin')} | **State:** {site.get('state', '')} | **Coordinates:** {lat}, {lon}")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("### Executive Summary & Intel")
            
            # --- The 30-Day Freshness Check ---
            last_updated = site.get('summary_generated_at')
            is_stale = True
            
            if pd.notna(last_updated) and last_updated:
                # Firestore returns timezone-aware datetimes. 
                delta_days = (datetime.now(timezone.utc) - last_updated).days
                if delta_days < 30:
                    is_stale = False
                st.caption(f"Last updated: {delta_days} days ago")
            else:
                st.caption("Never profiled.")

            if pd.notna(site.get('executive_summary')) and site.get('executive_summary'):
                st.info(site['executive_summary'])
            
            # Show the Refresh Button if Stale or Missing
            if is_stale:
                if st.button("✨ Run AI Profile Update", type="primary"):
                    with st.spinner(f"Deploying AI to research '{site.get('deposit_name')}'... this takes ~10 seconds."):
                        run_live_harvester(
                            doc_id=site['doc_id'], 
                            deposit_name=site.get('deposit_name', 'Unknown'), 
                            state=site.get('state', ''), 
                            feedstock_origin=site.get('feedstock_origin', '')
                        )
                        st.cache_data.clear()
                        st.rerun()
                
        with col2:
            st.markdown("### Discovered Sources & Links")
            sources = fetch_sources(site['doc_id'])
            if sources:
                for s in sources:
                    title = s.get('title', 'Target Link')
                    url = s.get('source_url', '#')
                    st.markdown(f"- **{title}** \n  [{url}]({url})")
            else:
                st.write("No external sources harvested yet.")
                
            ref_link = site.get('reference_link')
            if pd.notna(ref_link) and ref_link != "#":
                st.write("---")
                st.link_button("View Raw Database Source", ref_link)
                
    else:
        st.write("Details could not be resolved. Please try another pin.")
else:
    st.info("👆 Click a map pin above to load the AI-generated profile, executive summary, and source links.")
    
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