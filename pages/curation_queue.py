import os
import json
import streamlit as st
from google.cloud import firestore
import urllib.parse

st.set_page_config(page_title="Admin Curation Queue", layout="centered", page_icon="🗂️")

st.title("🗂️ Assay Document Curation")
st.caption("Admin-only queue to review unstructured documents before Gemini Pro extraction.")

# --- FIRESTORE INITIALIZATION ---
@st.cache_resource
def get_firestore_client():
    """Initializes Firestore using Streamlit secrets or local env variables."""
    try:
        if "gcp_service_account" in st.secrets:
            # Running on Streamlit Cloud
            creds_dict = json.loads(st.secrets["gcp_service_account"])
            return firestore.Client.from_service_account_info(creds_dict)
        else:
            # Running locally
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            return firestore.Client.from_service_account_json(key_path) if key_path else firestore.Client()
    except Exception as e:
        st.error(f"Firestore Initialization Error: {e}")
        return None

db = get_firestore_client()

if db is None:
    st.stop() # Halt execution if the database fails to connect

# --- SIMPLE ADMIN AUTHENTICATION ---
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["admin_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input("Enter Admin Password to access the queue:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error.
        st.text_input("Enter Admin Password to access the queue:", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

if check_password():
    # --- SECURE AREA: CURATION QUEUE ---
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

    pending_doc = fetch_pending_document()

    if pending_doc:
        st.info("Queue Active: Displaying next document pending review.")
        
        with st.container(border=True):
            st.subheader(pending_doc.get('document_title', 'Unknown Title'))
            
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
            
            # Action Buttons
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
        st.balloons()
        
    if st.button("Log Out"):
        st.session_state["password_correct"] = False
        st.rerun()