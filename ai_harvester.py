import os
import time
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------------------------------------------------------
# Configuration & Initialization
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# Load environment variables (This pulls in GOOGLE_APPLICATION_CREDENTIALS)
load_dotenv()

# Initialize Firebase Admin
# Because GOOGLE_APPLICATION_CREDENTIALS is set, we don't need to pass a 'cred' object
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()

# Initialize Gemini Client (assumes GEMINI_API_KEY is also in your environment)
ai_client = genai.Client()

# ---------------------------------------------------------
# Harvester Logic
# ---------------------------------------------------------
def run_ai_harvester(target_state: str, collection_name: str = "usmin_critical_minerals"):
    """
    Queries the specified collection for records matching the target state,
    generates an AI summary using Google Search grounding, and logs structured sources.
    """
    
    logging.info(f"Initiating AI harvester for '{collection_name}' targeting state: {target_state}")
    
    feedstocks_ref = db.collection(collection_name).where("state", "==", target_state)
    docs = feedstocks_ref.stream()
    
    processed_count = 0
    skipped_count = 0
    error_count = 0

    for doc in docs:
        data = doc.to_dict()
        doc_id = doc.id
        
        deposit_name = data.get("site_name") or data.get("deposit_name", "Unknown Deposit")
        feedstock_origin = data.get("feedstock_origin", "Geologic Deposit")
        
        # Idempotency Check
        if data.get("executive_summary"):
            logging.debug(f"Skipping {doc_id} - Summary already exists.")
            skipped_count += 1
            continue

        logging.info(f"Processing: {deposit_name} ({doc_id})")

        prompt = (
            f"Act as a critical minerals research assistant. Tell me about the '{deposit_name}' "
            f"located in {target_state}. It is classified as '{feedstock_origin}'. "
            f"Provide a concise executive summary (~200 words) detailing its geological context, "
            f"historical operations, and potential as a U.S. critical mineral or rare earth feedstock. "
            f"Include high-quality sources."
        )

        try:
            response = ai_client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}], 
                    temperature=0.2
                )
            )
            
            # 1. Update the main document
            doc_ref = db.collection(collection_name).document(doc_id)
            doc_ref.update({
                "executive_summary": response.text,
                "summary_generated_at": firestore.SERVER_TIMESTAMP
            })
            
            # 2. Extract and queue sources for Phase 2 wrangling
            if response.candidates and response.candidates[0].grounding_metadata:
                metadata = response.candidates[0].grounding_metadata
                
                if metadata.grounding_chunks:
                    sub_collection_ref = doc_ref.collection("unstructured_assets")
                    source_count = 0
                    
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
                            
                    logging.info(f"  -> Successfully generated summary and queued {source_count} sources.")
            
            processed_count += 1
            time.sleep(6) # Rate limiting to respect API quotas

        except Exception as e:
            logging.error(f"Failed to process {doc_id}: {e}")
            error_count += 1
            time.sleep(10) # Backoff on error

    logging.info("--- Harvester Run Complete ---")
    logging.info(f"Target State: {target_state} | Processed: {processed_count} | Skipped: {skipped_count} | Errors: {error_count}")

# ---------------------------------------------------------
# Execution
# ---------------------------------------------------------
if __name__ == "__main__":
    # Now you can easily change the state or loop through a list of states
    run_ai_harvester(target_state="CO")