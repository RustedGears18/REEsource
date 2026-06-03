import os
import json
import pandas as pd
import streamlit as st
from google.cloud import firestore
import urllib.parse

st.set_page_config(page_title="Admin Curation Queue", layout="wide", page_icon="🗂️")

st.title("🗂️ Assay Document Curation")
st.caption("Admin-only queue to review unstructured documents before Gemini Pro extraction.")

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

# --- SIMPLE ADMIN AUTHENTICATION ---
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["admin_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Admin Password to access the queue:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Admin Password to access the queue:", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if check_password():
    # --- SECURE AREA: MASTER ROSTER ---
    
    @st.cache_data(ttl=60) # Cache for 60 seconds to prevent spamming Firestore reads
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

    df_docs = fetch_all_documents()
    
    if not df_docs.empty:
        # Map raw database statuses to your preferred UI labels
        status_map = {
            'pending_manual_review': 'Unreviewed',
            'approved_for_extraction': 'Approved',
            'rejected': 'Rejected',
            'ingested_into_data_model': 'Ingested into Data Model'
        }
        df_docs['Status'] = df_docs['Raw_Status'].map(lambda x: status_map.get(x, x.replace('_', ' ').title()))
        
        # Apply your requested color coding
        def style_status(val):
            if val == 'Unreviewed':
                return 'color: #FFC107; font-weight: bold;' # Yellow
            elif val == 'Approved':
                return 'color: #4CAF50; font-weight: bold;' # Green
            elif val == 'Rejected':
                return 'color: #9E9E9E; font-style: italic;' # Gray/Disabled look
            elif val == 'Ingested into Data Model':
                return 'color: #2196F3; font-weight: bold;' # Blue
            return ''

        st.subheader("📋 Pipeline Status Roster")
        st.dataframe(
            df_docs[['Title', 'Year', 'Agency', 'Status']].style.map(style_status, subset=['Status']),
            use_container_width=True,
            hide_index=True
        )
        st.divider()

    # --- SECURE AREA: ACTIVE QUEUE ---
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
        db.collection('assay_documents').document(doc_id).update({
            'ingestion_status': new_status
        })
        fetch_all_documents.clear() # Clear the cache so the Master Roster updates instantly

    pending_doc = fetch_pending_document()

    if pending_doc:
        st.subheader("Active Review Queue")
        st.info("Displaying next document pending review.")
        
        with st.container(border=True):
            st.markdown(f"### {pending_doc.get('document_title', 'Unknown Title')}")
            
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
                if st.button("❌ Reject (Irrelevant)", type="primary", use_container_width=True):
                    update_status(pending_doc['doc_id'], 'rejected')
                    st.rerun()
            with btn_col3:
                if st.button("✅ Approve for Extraction", type="primary", use_container_width=True):
                    update_status(pending_doc['doc_id'], 'approved_for_extraction')
                    st.rerun()
    else:
        st.success("🎉 The curation queue is empty! All discovered documents have been reviewed.")
        
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("Log Out", type="secondary"):
        st.session_state["password_correct"] = False
        st.rerun()