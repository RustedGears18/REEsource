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

load_dotenv()

st.set_page_config(
    page_title="REEsource Geospatial Dashboard",
    page_icon="🌍",
    layout="wide"
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
    """
    Forces the LLM to output a strict JSON string separating the markdown profile 
    from the targeted REE estimation.
    """
    api_key = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
    
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        project_id = os.getenv("GCP_PROJECT_ID")
        if project_id:
            client = genai.Client(vertexai=True, project=project_id, location=os.getenv("GCP_LOCATION", "us-central1"))
        else:
            client = genai.Client()
            
    target_model = 'gemini-2.5-pro'
    
    prompt = f"""
    You are an expert geological data analyst. Create a highly detailed site profile for the '{deposit_data['deposit_name']}' deposit in {deposit_data['state']}.
    
    Strict Execution Guidelines:
    1. Total length of the profile must be approximately 1000 words.
    2. Provide exactly 10 accessible sources at the end.
    3. Sources MUST include a reference to the USGS MRDS data point URI: {deposit_data['source_link']}
    4. Prioritize sources from the USGS, Department of the Interior (DOI), and Army Corps of Engineers. Avoid pay-wall blocked sources entirely.
    5. Include a specific section titled "Environmental Issues and Ethics Concerns" (under 250 words, using up to 2 of the most relevant unbiased sources).
    6. Include a specific section titled "Recent Developments" (under 250 words, using up to 2 of the most relevant unbiased sources).
    7. NO CONVERSATIONAL FILLER. Do not include phrases like "Here is the profile" or "Sure, I can help".
    
    CRITICAL OUTPUT FORMAT:
    You must return your ENTIRE response as a valid JSON object. Do not wrap it in markdown block quotes. The JSON must exactly match this structure:
    {{
        "profile_content": "<The full markdown formatted 1000-word profile including all sections and sources.>",
        "ree_estimate": "<Based explicitly on the Geological Setting and Mineralogy sections of your profile, provide a 2-3 sentence estimation of the viability and potential presence of Rare Earth Elements (REEs) in this deposit.>"
    }}
    
    Available Site Context:
    - Deposit Type: {deposit_data.get('geology', {}).get('deposit_type')}
    - Operational Status: {deposit_data.get('operational_category')}
    - Size: {deposit_data.get('production_size')}
    - Primary Commodities: {', '.join(deposit_data.get('primary_commodities', []))}
    - Secondary Commodities: {', '.join(deposit_data.get('secondary_commodities', []))}
    - Ore Minerals: {deposit_data.get('ore_minerals')}
    - Gangue: {deposit_data.get('gangue_materials')}
    - Host Rock Type: {deposit_data.get('geology', {}).get('host_rock_type')}
    """
    
    response = client.models.generate_content(
        model=target_model,
        contents=prompt
    )
    
    # Safely strip potential markdown blocks from the JSON string
    raw_text = response.text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text.split("```", 1)[1].rsplit("```", 1)[0].strip()
        
    parsed_json = json.loads(raw_text)
    parsed_json['model_used'] = target_model
    return parsed_json

def main():
    st.title("REEsource: MRDS Feedstock Intelligence")
    st.markdown("### *Unearthing tomorrow's critical mineral supply*")
    
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
    
    default_state_index = available_states.index('COLORADO') if 'COLORADO' in available_states else 0
    selected_state = st.sidebar.selectbox("Select State", available_states, index=default_state_index)

    if selected_state != 'All US':
        filtered_df = filtered_df[filtered_df['state'] == selected_state]

    st.sidebar.header("Operational Filters")
    categories = ['All'] + sorted(filtered_df['operational_category'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Viability / Development Status", categories)

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['operational_category'] == selected_category]
        
    sizes = ['All'] + sorted(filtered_df['production_size'].dropna().unique().tolist())
    selected_size = st.sidebar.selectbox("Deposit Size", sizes)
    
    if selected_size != 'All':
        filtered_df = filtered_df[filtered_df['production_size'] == selected_size]

    st.sidebar.metric(label="Visible Targets", value=len(filtered_df))

    # --- ABOUT EXPANDER ---
    st.sidebar.markdown("---")
    with st.sidebar.expander("ℹ️ About REEsource"):
        st.markdown(
            "**REEsource** was developed as a capstone project for the Master of Science "
            "in Data Analytics program (IT Management specialization) at Colorado State University Global.\n\n"
            "This application provides end-to-end data infrastructure to evaluate the viability of "
            "critical mineral and Rare Earth Element (REE) feedstocks across the United States.\n\n"
            "🔗 [View the Project on GitHub](https://github.com/RustedGears18/REEsource)"
        )

    # --- DYNAMIC ZOOM LOGIC ---
    if target_deposit != 'None':
        target_row = df[df['deposit_name'] == target_deposit].iloc[0]
        map_center = [target_row['latitude'], target_row['longitude']]
        zoom_level = 12
    elif not filtered_df.empty:
        map_center = [filtered_df['latitude'].mean(), filtered_df['longitude'].mean()]
        zoom_level = 7 if selected_state != 'All US' else 4
    else:
        map_center = [39.8283, -98.5795]
        zoom_level = 4

    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles=None)

    # 1. Esri Satellite Layer (Default for high contrast with markers)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite Imagery (Default)',
        control=True
    ).add_to(m)

    # 2. USGS Topo Layer
    folium.TileLayer(
        tiles='https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
        attr='USGS The National Map',
        name='USGS Topo',
        control=True
    ).add_to(m)

    # 3. CartoDB Positron
    folium.TileLayer('CartoDB positron', name='Light Basemap', control=True).add_to(m)
    
    folium.LayerControl().add_to(m)

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
            radius=7 if sides < 30 else 5.5, 
            popup=folium.Popup(tooltip_text, max_width=350),
            tooltip=row.get('deposit_name', 'Unknown'),
            color="#1565c0",      # Darker blue border for crisp contrast
            weight=1.5,
            fill=True,
            fill_color="#3186cc",
            fill_opacity=1.0,     # 100% solid opacity
            opacity=1.0           # 100% solid border
        ).add_to(m)

    # --- RENDER MAP ---
    st_data = st_folium(m, width=1200, height=500, returned_objects=["last_object_clicked_tooltip"])

    # --- UI INTERMEDIATE CONTAINER: AI PROFILE ---
    st.divider()
    st.subheader("AI Feedstock Profile Engine")
    
    selected_deposit = None
    if st_data and st_data.get('last_object_clicked_tooltip'):
        selected_deposit = st_data['last_object_clicked_tooltip']
    elif target_deposit != 'None':
        selected_deposit = target_deposit

    if selected_deposit:
        selected_row = df[df['deposit_name'] == selected_deposit]
        
        if not selected_row.empty:
            target_data = selected_row.iloc[0].to_dict()
            doc_id = target_data['site_id']
            
            st.write(f"### Target View: **{selected_deposit}**")
            
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
                
                btn_color = "#81c784"
                btn_text = "Refresh Generative Site Profile"
            else:
                st.info("No detailed intelligence summary exists in the Firestore ledger for this deposit.")
                btn_color = "#2e7d32" 
                btn_text = "Execute Generative Site Profile"
                
            st.markdown(f"""
                <style>
                div.stButton > button:first-child {{
                    background-color: {btn_color};
                    color: white;
                    border: none;
                }}
                div.stButton > button:first-child:hover {{
                    background-color: #1b5e20;
                    color: white;
                }}
                </style>
            """, unsafe_allow_html=True)
                
            if st.button(btn_text):
                with st.spinner("Querying model and screening public datasets...(may take up to 60 seconds to refresh)"):
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
    else:
        st.write("*Click a map marker or choose a deposit from the sidebar search to execute dynamic deep-dive analysis.*")

    # --- UI PINNED TO BOTTOM: SPECIFICATIONS MASTER DATA TABLE ---
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