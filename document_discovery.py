import os
import json
import hashlib
import logging
import streamlit as st
from google.cloud import firestore
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Suppress verbose Google API logging 
logging.getLogger("google").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# ==========================================
# Core Client Initialization 
# ==========================================

def get_firestore_client():
    """Initializes Firestore using Streamlit secrets or fallback pathing."""
    try:
        # Check for Streamlit secrets first (for cloud deployment)
        try:
            if "gcp_service_account" in st.secrets:
                creds_dict = json.loads(st.secrets["gcp_service_account"])
                return firestore.Client.from_service_account_info(creds_dict)
        except Exception:
            pass # Fall through to local env vars if not running in Streamlit
            
        # Fallback for local environment
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path:
            return firestore.Client.from_service_account_json(key_path)
        return firestore.Client()
    except Exception as e:
        logging.error(f"Firestore Initialization Error: {e}")
        return None

def get_gemini_client():
    """Initializes Gemini using Streamlit secrets or local env variables."""
    try:
        api_key = None
        # Safely check secrets first
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            pass
        
        # Fallback to local environment
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            return genai.Client(api_key=api_key)
        
        # GCP Vertex fallback
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
    """Retrieves the ai_profiles subcollection data for a given MRDS deposit."""
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
    """Uses Gemini 2.5 Flash to identify likely unstructured ICP-MS assay documents."""
    target_model = 'gemini-2.5-flash'
    context_str = json.dumps(profile_data, indent=2)
    
    # Includes the 2010+ temporal constraints and APA 7 citation requirements
    prompt = f"""
    You are an expert metallurgical data engineer and mining researcher. 
    Below is the AI profile context for a targeted mining site.
    
    SITE CONTEXT:
    {context_str}
    
    HYPOTHESIS:
    This site was historically mined for a primary ore. However, it is highly probable that the resulting tailings, waste rock, or associated wastewaters have elevated Rare Earth Element (REE) concentrations.
    
    YOUR TASK:
    Identify 3 to 5 specific, real-world documents (PDFs, CSVs, technical reports, USGS Open-File Reports, environmental assessments) that are highly likely to contain unstructured ICP-MS assay data for this site.
    
    STRICT TEMPORAL CONSTRAINTS:
    - You MUST ONLY return documents published in the year 2010 or later.
    - Prioritize documents published from 2015 to the present day. 
    - Do not return historical, non-digitized reports from before 2010.
    
    OUTPUT FORMAT:
    You must return a valid JSON array of objects. Each object must have the following keys:
    - "document_title": (string) The likely formal title or name of the report/dataset.
    - "source_agency": (string) e.g., "USGS", "EPA", "Colorado DRMS", "Academic".
    - "publication_year": (integer) The year the document was published or last updated. Must be >= 2010.
    - "source_citation": (string) A full, structured APA 7 reference for this document.
    - "likely_format": (string) e.g., "PDF", "CSV", "Excel".
    - "relevance_justification": (string) Why this document likely contains ICP-MS REE data based on the site context.
    - "search_query": (string) A highly optimized Google search string to locate this exact document.
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
    """Ingests new documents or appends the deposit_id to existing ones."""
    if not documents:
        logging.warning("No documents to ingest.")
        return

    collection_ref = db.collection('assay_documents')
    count_new = 0
    count_updated = 0
    
    for doc in documents:
        # Create a deterministic ID based on the document title to handle deduplication
        doc_hash = hashlib.md5(doc['document_title'].encode('utf-8')).hexdigest()
        doc_ref = collection_ref.document(doc_hash)
        
        existing_doc = doc_ref.get()
        
        if existing_doc.exists:
            # Native GCP Firestore array union
            doc_ref.update({
                'tags': firestore.ArrayUnion([deposit_id])
            })
            count_updated += 1
        else:
            # New document ingestion
            doc['tags'] = [deposit_id]
            doc['ingestion_status'] = 'pending_manual_review' 
            doc['created_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.set(doc)
            count_new += 1
            
    logging.info(f"Success: {count_new} new docs added, {count_updated} existing docs tagged with {deposit_id}.")

# ==========================================
# Streamlit Dashboard Wrapper Function
# ==========================================

def run_discovery_pipeline(deposit_id):
    """
    Wrapper function intended to be called by an st.button in your Streamlit dashboard.
    Returns True if successful, False if no context was found or connections failed.
    """
    # Safety Check to prevent NoneType attribute errors
    if db is None or genai_client is None:
        logging.error("Cloud clients failed to initialize. Cannot run discovery pipeline.")
        return False

    profile_data = fetch_ai_profile(deposit_id)
    if not profile_data:
        return False
        
    discovered_docs = discover_assay_documents(profile_data)
    upsert_documents_to_firestore(deposit_id, discovered_docs)
    return True