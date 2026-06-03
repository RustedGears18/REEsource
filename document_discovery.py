import os
import json
import hashlib
import logging
import streamlit as st
from google.cloud import firestore
from google import genai
from google.genai import types
from dotenv import load_dotenv

logging.getLogger("google").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# ==========================================
# Core Client Initialization 
# ==========================================

def get_firestore_client():
    try:
        try:
            if "gcp_service_account" in st.secrets:
                creds_dict = json.loads(st.secrets["gcp_service_account"])
                return firestore.Client.from_service_account_info(creds_dict)
        except Exception:
            pass 
            
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path:
            return firestore.Client.from_service_account_json(key_path)
        return firestore.Client()
    except Exception as e:
        logging.error(f"Firestore Initialization Error: {e}")
        return None

def get_gemini_client():
    try:
        api_key = None
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            pass
        
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            return genai.Client(api_key=api_key)
        
        project_id = os.getenv("GCP_PROJECT_ID")
        if project_id:
            return genai.Client(vertexai=True, project=project_id, location=os.getenv("GCP_LOCATION", "us-central1"))
        
        return genai.Client()
    except Exception as e:
        logging.error(f"Gemini Initialization Error: {e}")
        return None

db = get_firestore_client()
genai_client = get_gemini_client()

# ==========================================
# Pipeline Functions
# ==========================================

def fetch_ai_profile(deposit_id):
    logging.info(f"Fetching ai_profiles for deposit: {deposit_id}...")
    profile_ref = db.collection('mrds_feedstock_profiles').document(deposit_id).collection('ai_profiles')
    docs = profile_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(1).stream()
    
    profile_data = {}
    for doc in docs:
        profile_data = doc.to_dict()
        
    if not profile_data:
        logging.warning(f"No ai_profiles found for {deposit_id}.")
    return profile_data

def discover_assay_documents(profile_data):
    """Uses Gemini 2.5 Flash to generate advanced search strategies for ICP-MS data."""
    target_model = 'gemini-2.5-flash'
    context_str = json.dumps(profile_data, indent=2)
    
    prompt = f"""
    You are an expert metallurgical data engineer and research librarian. 
    Below is the AI profile context for a targeted mining site.
    
    SITE CONTEXT:
    {context_str}
    
    HYPOTHESIS:
    This site was historically mined for a primary ore. However, it is highly probable that the resulting tailings, waste rock, or associated wastewaters have elevated Rare Earth Element (REE) concentrations.
    
    YOUR TASK:
    DO NOT invent or hallucinate specific document titles, authors, or citations. You do not have live internet access.
    Instead, generate 3 to 5 highly specific, advanced Google Search queries (Google Dorks) designed to uncover real-world unstructured ICP-MS assay data, tailings reports, or REE concentration measurements for this specific site published after 2010.
    
    OUTPUT FORMAT:
    You must return a valid JSON array of objects. Each object must have the following keys:
    - "target_document_type": (string) e.g., "USGS Open-File Report", "EPA Superfund Record of Decision", "Academic Thesis".
    - "search_strategy_rationale": (string) Why this specific search strategy is likely to yield REE assay data for this site.
    - "optimized_google_dork": (string) An advanced Google search string utilizing operators (e.g., `"Urad Mine" AND ("ICP-MS" OR "rare earth") filetype:pdf site:usgs.gov`).
    - "publication_year_target": (string) "Post-2010" or "Post-2015".
    """

    try:
        response = genai_client.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        logging.error(f"Error querying Gemini or parsing response: {e}")
        return []

def upsert_documents_to_firestore(deposit_id, documents):
    if not documents:
        logging.warning("No documents to ingest.")
        return

    collection_ref = db.collection('assay_documents')
    count_new = 0
    count_updated = 0
    
    for doc in documents:
        # Use the google dork as the unique hash to prevent duplicate search strategies
        doc_hash = hashlib.md5(doc['optimized_google_dork'].encode('utf-8')).hexdigest()
        doc_ref = collection_ref.document(doc_hash)
        
        existing_doc = doc_ref.get()
        
        if existing_doc.exists:
            doc_ref.update({
                'tags': firestore.ArrayUnion([deposit_id])
            })
            count_updated += 1
        else:
            doc['tags'] = [deposit_id]
            doc['ingestion_status'] = 'pending_manual_review' 
            doc['verified_url'] = "" # Initialize empty for manual data entry later
            doc['created_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.set(doc)
            count_new += 1
            
    logging.info(f"Success: {count_new} new strategies added, {count_updated} existing strategies tagged with {deposit_id}.")

def run_discovery_pipeline(deposit_id):
    if db is None or genai_client is None:
        logging.error("Cloud clients failed to initialize. Cannot run discovery pipeline.")
        return False

    profile_data = fetch_ai_profile(deposit_id)
    if not profile_data:
        return False
        
    discovered_docs = discover_assay_documents(profile_data)
    upsert_documents_to_firestore(deposit_id, discovered_docs)
    return True