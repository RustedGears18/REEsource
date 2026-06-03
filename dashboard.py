import os
import streamlit as st
from google.cloud import firestore
import pandas as pd
import folium
from streamlit_folium import st_folium
import json 
import urllib.parse
from datetime import datetime
from google import genai
from dotenv import load_dotenv

# --- NEW IMPORT ---
from document_discovery import run_discovery_pipeline

load_dotenv()

st.set_page_config(
    page_title="REEsource Geospatial Dashboard",
    page_icon="🌍",
    layout="wide"
)

# --- RESPONSIVE CSS INJECTION (MARGIN & MAP SCALING) ---
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 1.5rem !important;
    }
    iframe {
        height: 82vh !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- BRANDING & ASSETS ---
logo_path = os.path.join("assets", "REEsource brand dark.png")
if os.path.exists(logo_path):
    st.sidebar.image(logo_path, width="stretch")
else:
    st.sidebar.title("REEsource")
st.sidebar.divider()

def get_firestore_client():
    """Initializes Firestore using environment variables or fallback pathing."""
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
    if not db: return pd.DataFrame()
    try:
        docs = db.collection(collection_name).stream()
        data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            doc_dict['site_id'] = doc.id 
            
            if 'location' in doc_dict and doc_dict['location']:
                doc_dict['latitude'] = doc_dict['location'].get('latitude')
                doc_dict['longitude'] = doc_dict['location'].get('longitude')
                
            doc_dict['sec_comms_str'] = ", ".join(doc_dict.get('secondary_commodities', []))
            data.append(doc_dict)
        
        return pd.DataFrame(data).dropna(subset=['latitude', 'longitude']) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"Firestore Query Error: {e}")
        return pd.DataFrame()

def get_mrds_symbology(status):
    status = str(status).lower()
    if 'producer' in status:
        return 4, 45  
    elif 'plant' in status:
        return 3, 0   
    else:
        return 30, 0  

def generate_ai_profile(deposit_data):
    api_key = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        project_id = os.getenv("GCP_PROJECT_ID")
        if project_id:
            client = genai.Client(vertexai=True, project=project_id, location=os.getenv("GCP_LOCATION", "us-central1"))
        else:
            client = genai.Client()
            
    target_model = 'gemini-2.5-flash'
    
    prompt = f"""
    You are an expert geological data analyst. Create a highly detailed site profile for the '{deposit_data['deposit_name']}' deposit in {deposit_data['state']}.
    
    Strict Execution Guidelines:
    1. Total length of the profile must be approximately 1000 words.
    2. Provide exactly 10 accessible sources at the end.
    3. Sources MUST include a reference to the USGS MRDS data point URI: {deposit_data['source_link']}
    4. Prioritize sources from the USGS, Department of the Interior (DOI), and Army Corps of Engineers. Avoid pay-wall blocked sources entirely.
    5. Include a specific section titled "Environmental Issues and Ethics Concerns" (under 250 words, using up to 2 of the most relevant unbiased sources).
    6. Include a specific section titled "Recent Developments" (under 250 words, using up to 2 of the most relevant unbiased sources).
    7. NO CONVERSATIONAL FILLER.
    
    CRITICAL OUTPUT FORMAT:
    You must return your ENTIRE response as a valid JSON object. Do not wrap it in markdown block quotes. The JSON must exactly match this structure:
    {{
        "profile_content": "<The full markdown formatted 1000-word profile including all sections and sources.>",
        "ree_estimate": "<Based explicitly on the Geological Setting and Mineralogy sections of your profile, provide a 2-3 sentence estimation of the viability and potential presence of Rare Earth Elements (REEs) in this deposit.>"
    }}
    """
    
    # Using the updated SDK typing for consistency
    response = client.models.generate_content(
        model=target_model, 
        contents=prompt
    )
    raw_text = response.text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text.split("```", 1)[1].rsplit("```", 1)[0].strip()
        
    parsed_json = json.loads(raw_text)
    parsed_json['model_used'] = target_model
    return parsed_json

def main():
    # Initialize session state for tracking toasts
    if 'last_viewed_deposit' not in st.session_state:
        st.session_state['last_viewed_deposit'] = None

    with st.spinner("Connecting to Google Cloud Firestore..."):
        df = fetch_firestore_data()

    if df.empty:
        st.error("No coordinate data found in the Firestore database.")
        return

    df['reference_link'] = df.apply(generate_healing_link, axis=1)
    filtered_df = df.copy()

    # --- SIDEBAR SEARCH & FILTERS ---
    st.sidebar.header("Explore Filters")
    search_list = ['None'] + sorted(filtered_df['deposit_name'].dropna().unique().tolist())
    target_deposit = st.sidebar.selectbox("Find Specific Deposit...", search_list)
    
    st.sidebar.subheader("Location")
    
    raw_states = df['state'].dropna().unique().tolist()
    cleaned_states = set()
    for s in raw_states:
        if s not in ['None', 'UNKNOWN']:
            for part in s.split(','):
                clean_part = part.strip().upper()
                if clean_part:
                    cleaned_states.add(clean_part)
                    
    available_states = ['All US'] + sorted(list(cleaned_states))
    default_state_index = available_states.index('COLORADO') if 'COLORADO' in available_states else 0
    selected_state = st.sidebar.selectbox("Select State", available_states, index=default_state_index)

    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'].fillna('').str.contains(selected_state)]

    st.sidebar.subheader("Operations")
    categories = ['All'] + sorted(filtered_df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Viability / Development Status", categories)

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]
        
    sizes = ['All'] + sorted(filtered_df['production_size'].dropna().unique().tolist())
    selected_size = st.sidebar.selectbox("Deposit Size", sizes)
    
    if selected_size != 'All':
        filtered_df = filtered_df[filtered_df['production_size'] == selected_size]

    st.sidebar.metric(label="Visible Targets", value=len(filtered_df))

    # --- SIDEBAR EXPANDERS ---
    st.sidebar.markdown("---")
    
    with st.sidebar.expander("📖 Quick Definitions"):
        st.markdown("**Critical Mineral:**")
        st.write("A non-fuel mineral or mineral material essential to the economic and national security of the United States, the supply chain of which is vulnerable to disruption.")
        st.markdown("**Rare Earth Element (REE):**")
        st.write("A set of 17 chemically similar metallic elements (the 15 lanthanides plus scandium and yttrium), critical for high-tech, defense, and advanced metallurgical applications.")

    with st.sidebar.expander("ℹ️ About REEsource"):
        st.markdown(
            "**REEsource** was developed as a capstone project for the Master of Science "
            "in Data Analytics program (IT Management specialization) at Colorado State University Global.\n\n"
            "This application provides end-to-end data infrastructure to evaluate the viability of "
            "critical mineral and Rare Earth Element (REE) feedstocks across the United States.\n\n"
            "🔗 [View the Project on GitHub](https://github.com/RustedGears18/REEsource)"
        )

    # --- DYNAMIC MAP BOUNDING ---
    if not filtered_df.empty:
        # Find the geographic edges of the current filtered dataset
        min_lat = filtered_df['latitude'].min()
        max_lat = filtered_df['latitude'].max()
        min_lon = filtered_df['longitude'].min()
        max_lon = filtered_df['longitude'].max()
        
        # Calculate the mathematical center
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        
        m = folium.Map(location=[center_lat, center_lon], tiles=None)
        
        # Instruct Folium to frame the map perfectly around these edges
        m.fit_bounds(
            [[min_lat, min_lon], [max_lat, max_lon]], 
            padding=(30, 30),
            max_zoom=12 # Prevents the map from uncomfortably deep-zooming if only a single mine is selected
        )
    else:
        # Fallback to the geographic center of the US if filters yield zero results
        m = folium.Map(location=[39.8283, -98.5795], zoom_start=4, tiles=None)

    # --- STATIC LAYER RENDERING ---
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Topographic', control=True, show=True
    ).add_to(m)

    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Satellite Imagery', control=True, show=False
    ).add_to(m)

    folium.TileLayer(
        tiles='https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
        attr='USGS The National Map', name='USGS Topo', control=True, show=False
    ).add_to(m)

    folium.TileLayer('CartoDB positron', name='Light Basemap', control=True, show=False).add_to(m)
    
    folium.LayerControl().add_to(m)

    # Map Markers
    for _, row in filtered_df.iterrows():
        sides, rot = get_mrds_symbology(row.get('operational_category'))
        summary = row.get('feedstock_summary', 'No summary available.')
        
        tooltip_text = f"<b>{row.get('deposit_name', 'Unknown')}</b><br>" \
                       f"State: {row.get('state', 'Unknown')}<br>" \
                       f"Status: {row.get('operational_category', 'Unknown')}<br><br>" \
                       f"<i>{summary}</i><br><br>" \
                       f"<span style='color: gray; font-style: italic; font-size: 0.9em;'>*see more information below</span>"
                       
        folium.RegularPolygonMarker(
            location=[row['latitude'], row['longitude']],
            number_of_sides=sides,
            rotation=rot,
            radius=7 if sides < 30 else 5.5, 
            popup=folium.Popup(tooltip_text, max_width=350),
            tooltip=row.get('deposit_name', 'Unknown'),
            color="#1565c0",
            weight=1.5,
            fill=True,
            fill_color="#3186cc",
            fill_opacity=1.0,
            opacity=1.0
        ).add_to(m)

    st_data = st_folium(m, use_container_width=True, returned_objects=["last_object_clicked_tooltip"])
    
    st.caption("USGS 'Grade A' Mine data only; filter the map or click on a deposit for more information.")

    # --- DEPOSIT DETAILS (CONDITIONAL) ---
    selected_deposit = None
    if st_data and st_data.get('last_object_clicked_tooltip'):
        selected_deposit = st_data['last_object_clicked_tooltip']
    elif target_deposit != 'None':
        selected_deposit = target_deposit

    if selected_deposit:
        if selected_deposit != st.session_state['last_viewed_deposit']:
            st.toast(f"Data loaded for {selected_deposit}! Scroll down to view.", icon="⬇️")
            st.session_state['last_viewed_deposit'] = selected_deposit
            
        st.divider()
        
        st.markdown(
            f"""
            <div style="padding: 1.5rem; background-color: rgba(21, 101, 192, 0.05); border-left: 6px solid #1565c0; border-radius: 0.5rem; margin-bottom: 1.5rem;">
                <h2 style="margin-top: 0; margin-bottom: 0.5rem; color: #1565c0;">Deposit Details</h2>
                <span style="color: #424242; font-size: 1.1em;">Target View: <strong>{selected_deposit}</strong></span>
            </div>
            """, 
            unsafe_allow_html=True
        )
        
        selected_row = df[df['deposit_name'] == selected_deposit]
        
        if not selected_row.empty:
            target_data = selected_row.iloc[0].to_dict()
            doc_id = target_data['site_id']
            
            subcol_ref = db.collection('mrds_feedstock_profiles').document(doc_id).collection('ai_profiles')
            existing_profiles = list(subcol_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(1).stream())
            
            if existing_profiles:
                profile_data = existing_profiles[0].to_dict()
                
                ree_estimate = profile_data.get('ree_estimate')
                if ree_estimate:
                    st.info(f"🌍 **Estimated Viable REE Presence:**\n\n{ree_estimate}")
                    
                st.markdown(profile_data.get('content'))
                
                model_used = profile_data.get('model_used', 'gemini-2.5-flash')
                st.caption(f"✨ *This Geological Site Profile was compiled by Google {model_used} on {profile_data.get('created_at')}*")
                
                # --- ACTION BUTTONS (COLUMNS) ---
                st.write("### AI Agent Actions")
                col1, col2 = st.columns(2)
                
                with col1:
                    # Streamlit native primary button styling is cleaner than injecting custom CSS 
                    # but we will use type="secondary" here so the document search stands out.
                    if st.button("🔄 Refresh Generative Profile", type="secondary", use_container_width=True):
                        with st.spinner("Querying model and screening public datasets...(may take up to 60 seconds)"):
                            try:
                                ai_data = generate_ai_profile(target_data)
                                subcol_ref.add({
                                    'content': ai_data.get('profile_content', ''),
                                    'ree_estimate': ai_data.get('ree_estimate', ''),
                                    'model_used': ai_data.get('model_used', 'Unknown Model'),
                                    'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                st.success("Analysis complete. Data committed to Firestore subcollection.")
                                st.rerun()
                            except Exception as gen_err:
                                st.error(f"GenAI Token or Parsing Error: {gen_err}")
                
                with col2:
                    # The new document discovery trigger
                    if st.button("🔍 Search Unstructured Assay Docs", type="primary", use_container_width=True):
                        with st.spinner("Dispatching Gemini to identify high-probability ICP-MS document targets..."):
                            success = run_discovery_pipeline(doc_id)
                            if success:
                                st.success("Document discovery complete! Check Firestore ('assay_documents' collection) for pending reviews.")
                            else:
                                st.error("Discovery failed. Ensure the AI profile context exists and Firestore is connected.")
            else:
                st.info("No detailed intelligence summary exists in the Firestore ledger for this deposit.")
                
                # If no profile exists, they can only generate one (can't search for docs yet)
                if st.button("Execute Generative Site Profile", type="primary"):
                    with st.spinner("Querying model and screening public datasets...(may take up to 60 seconds)"):
                        try:
                            ai_data = generate_ai_profile(target_data)
                            
                            subcol_ref.add({
                                'content': ai_data.get('profile_content', ''),
                                'ree_estimate': ai_data.get('ree_estimate', ''),
                                'model_used': ai_data.get('model_used', 'Unknown Model'),
                                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            st.success("Analysis complete. Data committed to Firestore subcollection.")
                            st.rerun()
                        except Exception as gen_err:
                            st.error(f"GenAI Token or Parsing Error: {gen_err}")

    # --- SPECIFICATIONS MASTER DATA TABLE ---
    st.divider()
    st.subheader("Extracted Site Specifications (Filtered Universe)")
    st.dataframe(
        filtered_df[[
            'deposit_name', 'state', 'production_size', 'operational_category', 
            'sec_comms_str', 'cm_present', 'disc_yr', 'yr_fst_prd', 'ref', 'reference_link'
        ]],
        column_config={
            "deposit_name": "Deposit",
            "state": "State",
            "production_size": "Size",
            "operational_category": "Status",
            "sec_comms_str": "Secondary Commodities",
            "cm_present": "Crit. Mins (Viable)",
            "disc_yr": "Disc. Year",
            "yr_fst_prd": "1st Prod. Year",
            "ref": "USGS Reference(s)",
            "reference_link": st.column_config.LinkColumn("Source / Location", display_text=r"^(?:https?:\/\/(?:www\.)?)?(.{0,30})")
        },
        hide_index=True,
        width="stretch"
    )

if __name__ == "__main__":
    main()