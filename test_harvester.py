import os
import time
import logging
import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore import FieldFilter
from google import genai
from google.genai import types
from dotenv import load_dotenv

# ---------------------------------------------------------
# Configuration & Initialization
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

load_dotenv()

# 1. Initialize Firestore 
if not firebase_admin._apps:
    firebase_admin.initialize_app()
db = firestore.client()

# 2. Initialize Gemini via Vertex AI
# ** Replace 'your-gcp-project-id' with your actual REEsource project ID! **
gcp_project_id = "reesource" 

logging.info(f"Connecting to Vertex AI in project: {gcp_project_id}")
ai_client = genai.Client(
    vertexai=True, 
    project=gcp_project_id, 
    location="us-central1" 
)

# ---------------------------------------------------------
# Single Record Test Logic
# ---------------------------------------------------------
def test_single_record(target_state="CO", collection_name="usmin_critical_minerals"):
    
    logging.info(f"Querying Firestore for 1 record in {target_state}...")
    
    # We use .limit(1) to ensure we only process exactly one record for this test
    feedstocks_ref = db.collection(collection_name).where(filter=FieldFilter("state", "==", target_state)).limit(1)
    docs = feedstocks_ref.stream()
    
    doc_processed = False

    for doc in docs:
        data = doc.to_dict()
        doc_id = doc.id
        doc_processed = True
        
        deposit_name = data.get("site_name") or data.get("deposit_name", "Unknown Deposit")
        feedstock_origin = data.get("feedstock_origin", "Geologic Deposit")
        
        logging.info(f"🔥 Found Test Target: {deposit_name} (ID: {doc_id})")

        prompt = (
            f"Act as a critical minerals research assistant. Tell me about the '{deposit_name}' "
            f"located in {target_state}. It is classified as '{feedstock_origin}'. "
            f"Provide a concise executive summary (~200 words) detailing its geological context, "
            f"historical operations, and potential as a U.S. critical mineral or rare earth feedstock. "
            f"Include high-quality sources."
        )

        try:
            logging.info("🧠 Sending prompt to Gemini 2.5 Pro (with Search Grounding)...")
            response = ai_client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}], 
                    temperature=0.2
                )
            )
            
            logging.info("✅ Received response. Writing Executive Summary to main document...")
            
            # Write to Main Document
            doc_ref = db.collection(collection_name).document(doc_id)
            doc_ref.update({
                "executive_summary": response.text,
                "summary_generated_at": firestore.SERVER_TIMESTAMP
            })
            
            # Extract Sources
            if response.candidates and response.candidates[0].grounding_metadata:
                metadata = response.candidates[0].grounding_metadata
                
                if metadata.grounding_chunks:
                    sub_collection_ref = doc_ref.collection("unstructured_assets")
                    source_count = 0
                    
                    logging.info(f"🔍 Extracting {len(metadata.grounding_chunks)} grounding links...")
                    
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
                            source_count += 1
                            logging.info(f"  -> Saved source: {chunk.web.title}")
                            
            logging.info(f"🎉 Test complete! Updated 1 main doc and nested {source_count} sources.")

        except Exception as e:
            logging.error(f"❌ Test Failed. Error details: {e}")

    if not doc_processed:
        logging.warning(f"No documents found for state {target_state} in collection {collection_name}.")

if __name__ == "__main__":
    test_single_record()