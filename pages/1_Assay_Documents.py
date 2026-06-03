import os
import json
import pandas as pd
import streamlit as st
from google.cloud import firestore
import urllib.parse

st.set_page_config(page_title="Assay Documents", layout="wide", page_icon="📄")

# --- FIRESTORE INITIALIZATION ---
@st.cache_resource
def get_firestore_client():
    """Initializes Firestore using Streamlit secrets or local env variables."""
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

# --- SIDEBAR ADMIN AUTHENTICATION ---
def check_admin_status():
    """Renders a subtle login in the sidebar and returns True if authenticated."""
    if st.session_state.get("admin_authenticated", False):
        with st.sidebar:
            st.divider()
            st.success("🔓 Admin Mode Active")
            if st.button("Log Out"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return True

    with st.sidebar:
        st.divider()
        st.caption("Admin Access")
        def password_entered():
            if st.session_state["pwd_input"] == st.secrets["admin_password"]:
                st.session_state["admin_authenticated"] = True
                del st.session_state["pwd_input"]  # Clean up memory
            else:
                st.session_state["admin_authenticated"] = False

        st.text_input("Enter Password", type="password", on_change=password_entered, key="pwd_input", label_visibility="collapsed")
        
        if "admin_authenticated" in st.session_state and not st.session_state["admin_authenticated"]:
            st.error("Incorrect password")
            
    return False

# --- DATA FETCHING ---
@st.cache_data(ttl=60) 
def fetch_all_documents():
    docs = db.collection('assay_documents').stream()
    doc_list = []
    for d in docs:
        data = d.to_dict()
        doc_list.append({
            'Title': data.get('document_title', 'Unknown'),
            'Agency': data.get('source_agency', 'N/A'),
            'Year': data.get('publication_year', 'N/A'),
            'Raw_Status': data.get('ingestion_status', 'Unknown')
        })
    return pd.DataFrame(doc_list)

# Determine user state
is_admin = check_admin_status()

st.title("📄 Discovered Assay Documents")
st.caption("A public repository of unstructured geological datasets and historical reports identified by the REEsource AI Agent.")

# ==========================================
# SECURE AREA: ACTIVE QUEUE (ONLY VISIBLE TO ADMINS)
# ==========================================
if is_admin:
    st.markdown("""
        <div style="padding: 1rem; background-color: rgba(255, 193, 7, 0.1); border-left: 5px solid #FFC107; border-radius: 0.5rem; margin-bottom: 2rem;">
            <h3 style="margin-top: 0; color: #FFC107;">🗂️ Active Curation Queue</h3>
            <span style="color: #E0E0E0;">Review unstructured documents before passing them to the extraction pipeline.</span>
        </div>
    """, unsafe_allow_html=True)

    def fetch_pending_document():
        docs = db.collection('assay_documents').where(
            filter=firestore.FieldFilter('ingestion_status', '==', 'pending_manual_review')
        ).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = doc.id
            return data
        return None

    def update_status(doc_id, new_status):
        db.collection('assay_documents').document(doc_id).update({'ingestion_status': new_status})
        fetch_all_documents.clear() # Force public table to update instantly

    pending_doc = fetch_pending_document()

    if pending_doc:
        with st.container(border=True):
            st.markdown(f"#### {pending_doc.get('document_title', 'Unknown Title')}")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Year", pending_doc.get('publication_year', 'N/A'))
            col2.metric("Agency", pending_doc.get('source_agency', 'N/A'))
            col3.metric("Format", pending_doc.get('likely_format', 'N/A'))
            
            st.markdown("**APA 7 Citation:**")
            st.code(pending_doc.get('source_citation', 'Citation missing.'), language="markdown")
            
            st.markdown("**AI Relevance Justification:**")
            st.write(pending_doc.get('relevance_justification', 'No justification provided.'))
            
            query = pending_doc.get('search_query', pending_doc.get('document_title'))
            google_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            st.markdown(f"🔍 **[Search Google for Document Source]({google_url})**")
            
            st.divider()
            
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
            with btn_col1:
                if st.button("❌ Reject (Irrelevant)", type="secondary", use_container_width=True):
                    update_status(pending_doc['doc_id'], 'rejected')
                    st.rerun()
            with btn_col3:
                if st.button("✅ Approve for Extraction", type="primary", use_container_width=True):
                    update_status(pending_doc['doc_id'], 'approved_for_extraction')
                    st.rerun()
    else:
        st.success("🎉 The curation queue is empty! All pending documents have been reviewed.")
        
    st.divider()

# ==========================================
# PUBLIC AREA: PIPELINE STATUS ROSTER
# ==========================================
df_docs = fetch_all_documents()

if not df_docs.empty:
    status_map = {
        'pending_manual_review': 'Unreviewed',
        'approved_for_extraction': 'Approved',
        'rejected': 'Rejected',
        'ingested_into_data_model': 'Ingested into Data Model'
    }
    df_docs['Status'] = df_docs['Raw_Status'].map(lambda x: status_map.get(x, x.replace('_', ' ').title()))
    
    def style_status(val):
        if val == 'Unreviewed': return 'color: #FFC107; font-weight: bold;'
        elif val == 'Approved': return 'color: #4CAF50; font-weight: bold;'
        elif val == 'Rejected': return 'color: #9E9E9E; font-style: italic;'
        elif val == 'Ingested into Data Model': return 'color: #2196F3; font-weight: bold;'
        return ''

    st.subheader("📋 Pipeline Status Roster")
    st.dataframe(
        df_docs[['Title', 'Year', 'Agency', 'Status']].style.map(style_status, subset=['Status']),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No unstructured documents have been discovered by the AI agent yet. Use the geospatial map to trigger a discovery search.")