import os
import json
import pandas as pd
import streamlit as st
from google.cloud import firestore

st.set_page_config(page_title="Assay Documents Repository", layout="wide", page_icon="📄")

# --- FIRESTORE INITIALIZATION ---
@st.cache_resource
def get_firestore_client():
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

if db is None:
    st.stop()

# --- DATA FETCHING ---
@st.cache_data(ttl=60) 
def fetch_curated_documents():
    docs = db.collection('assay_documents').stream()
    doc_list = []
    for d in docs:
        data = d.to_dict()
        doc_list.append({
            'Target Deposit': data.get('deposit_name', 'Unknown'),
            'Document Title': data.get('document_title', 'Unknown'),
            'Verified URL': data.get('verified_url', ''),
            'Pipeline Status': data.get('status', 'Unknown')
        })
    return pd.DataFrame(doc_list)

st.title("📄 Curated Assay Document Repository")
st.caption("A master roster of verified, unstructured geological datasets slated for REE concentration extraction.")
st.divider()

df_docs = fetch_curated_documents()

if not df_docs.empty:
    def style_status(val):
        if val == 'Pending Extraction': return 'color: #FFC107; font-weight: bold;'
        elif val == 'Extraction Complete': return 'color: #4CAF50; font-weight: bold;'
        return ''

    st.dataframe(
        df_docs.style.map(style_status, subset=['Pipeline Status']),
        column_config={
            "Verified URL": st.column_config.LinkColumn("Source Link")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No documents have been manually curated yet. Use the geospatial map to locate a deposit, generate search strategies, and ingest a verified document URL.")