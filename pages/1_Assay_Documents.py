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
                del st.session_state["pwd_input"] 
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
            'Target Document': data.get('target_document_type', 'Unknown'),
            'Temporal Range': data.get('publication_year_target', 'N/A'),
            'Tags': ", ".join(data.get('tags', [])),
            'Raw_Status': data.get('ingestion_status', 'Unknown')
        })
    return pd.DataFrame(doc_list)

is_admin = check_admin_status()

st.title("📄 Unstructured Assay Discovery")
st.caption("A public repository of advanced AI-generated search strategies designed to identify REE concentrations in historical tailings.")

# ==========================================
# SECURE AREA: ACTIVE QUEUE 
# ==========================================
if is_admin:
    st.markdown("""
        <div style="padding: 1rem; background-color: rgba(255, 193, 7, 0.1); border-left: 5px solid #FFC107; border-radius: 0.5rem; margin-bottom: 2rem;">
            <h3 style="margin-top: 0; color: #FFC107;">🗂️ Active Curation Queue</h3>
            <span style="color: #E0E0E0;">Execute strategies, verify document access, and ingest valid URLs for the extraction pipeline.</span>
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

    pending_doc = fetch_pending_document()

    if pending_doc:
        with st.container(border=True):
            st.markdown(f"#### Target: {pending_doc.get('target_document_type', 'Unknown Document Type')}")
            
            col1, col2 = st.columns(2)
            col1.metric("Temporal Target", pending_doc.get('publication_year_target', 'N/A'))
            col2.metric("Status", "Pending Search Execution")
            
            st.markdown("**Search Strategy Rationale:**")
            st.write(pending_doc.get('search_strategy_rationale', 'No rationale provided.'))
            
            st.markdown("**Optimized Google Dork:**")
            query = pending_doc.get('optimized_google_dork', '')
            st.code(query, language="sql")
            
            google_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            st.markdown(f"### 🔍 **[Execute Targeted Search on Google]({google_url})**")
            
            st.divider()
            
            # The URL Ingestion Field
            verified_url = st.text_input("🔗 Verified Document URL (Paste here after searching):", placeholder="https://pubs.usgs.gov/...", help="Must be a direct link to the unstructured document.")
            
            st.markdown("<br>", unsafe_allow_html=True)
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
            
            with btn_col1:
                if st.button("❌ Reject Strategy (Dead End)", type="secondary", use_container_width=True):
                    db.collection('assay_documents').document(pending_doc['doc_id']).update({'ingestion_status': 'rejected'})
                    fetch_all_documents.clear()
                    st.rerun()
                    
            with btn_col3:
                if st.button("✅ Approve & Ingest URL", type="primary", use_container_width=True):
                    if not verified_url:
                        st.error("You must provide a verified URL to approve this strategy and move it to extraction.")
                    else:
                        db.collection('assay_documents').document(pending_doc['doc_id']).update({
                            'ingestion_status': 'approved_for_extraction',
                            'verified_url': verified_url
                        })
                        fetch_all_documents.clear()
                        st.rerun()
    else:
        st.success("🎉 The curation queue is empty! All pending strategies have been reviewed.")
        
    st.divider()

# ==========================================
# PUBLIC AREA: PIPELINE STATUS ROSTER
# ==========================================
df_docs = fetch_all_documents()

if not df_docs.empty:
    status_map = {
        'pending_manual_review': 'Unreviewed Strategy',
        'approved_for_extraction': 'URL Ingested (Approved)',
        'rejected': 'Dead End (Rejected)',
        'ingested_into_data_model': 'Extraction Complete'
    }
    df_docs['Status'] = df_docs['Raw_Status'].map(lambda x: status_map.get(x, x.replace('_', ' ').title()))
    
    def style_status(val):
        if val == 'Unreviewed Strategy': return 'color: #FFC107; font-weight: bold;'
        elif val == 'URL Ingested (Approved)': return 'color: #4CAF50; font-weight: bold;'
        elif val == 'Dead End (Rejected)': return 'color: #9E9E9E; font-style: italic;'
        elif val == 'Extraction Complete': return 'color: #2196F3; font-weight: bold;'
        return ''

    st.subheader("📋 Pipeline Status Roster")
    st.dataframe(
        df_docs[['Target Document', 'Temporal Range', 'Tags', 'Status']].style.map(style_status, subset=['Status']),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No search strategies have been generated by the AI agent yet. Use the geospatial map to trigger a discovery search.")