import os
import json
import time
import logging
from datetime import datetime
import concurrent.futures
from google.cloud import firestore
from google import genai
from dotenv import load_dotenv
from tqdm import tqdm

# Suppress verbose Google API logging
logging.getLogger("google").setLevel(logging.WARNING)

load_dotenv()

def get_firestore_client():
    try:
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path:
            return firestore.Client.from_service_account_json(key_path)
        return firestore.Client()
    except Exception as e:
        print(f"❌ Firestore Initialization Error: {e}")
        return None

def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key)
    
    project_id = os.getenv("GCP_PROJECT_ID")
    if project_id:
        return genai.Client(vertexai=True, project=project_id, location=os.getenv("GCP_LOCATION", "us-central1"))
    
    return genai.Client()

def generate_ai_profile_with_retry(client, deposit_data, max_retries=3):
    """Executes the exact prompt from dashboard.py, with exponential backoff for rate limits."""
    target_model = 'gemini-2.5-flash'
    
    prompt = f"""
    You are an expert geological data analyst. Create a highly detailed site profile for the '{deposit_data['deposit_name']}' deposit in {deposit_data['state']}.
    
    Strict Execution Guidelines:
    1. Total length of the profile must be approximately 1000 words.
    2. Provide exactly 10 accessible sources at the end.
    3. Sources MUST include a reference to the USGS MRDS data point URI: {deposit_data.get('source_link', 'N/A')}
    4. Prioritize sources from the USGS, Department of the Interior (DOI), and Army Corps of Engineers. Avoid pay-wall blocked sources entirely.
    5. Include a specific section titled "Environmental Issues and Ethics Concerns" (under 250 words, using up to 2 of the most relevant unbiased sources).
    6. Include a specific section titled "Recent Developments" (under 250 words, using up to 2 of the most relevant unbiased sources).
    7. NO CONVERSATIONAL FILLER.
    
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
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=target_model, contents=prompt)
            raw_text = response.text.strip()
            
            # Clean markdown formatting if the model wraps the JSON
            if raw_text.startswith("```json"):
                raw_text = raw_text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.split("```", 1)[1].rsplit("```", 1)[0].strip()
                
            parsed_json = json.loads(raw_text)
            parsed_json['model_used'] = target_model
            return parsed_json
            
        except Exception as e:
            if attempt == max_retries - 1:
                raise Exception(f"Failed after {max_retries} attempts. Last error: {e}")
            time.sleep(2 ** attempt) # Exponential backoff: 1s, 2s, 4s...

def process_single_deposit(db, genai_client, doc_id, doc_data):
    """Worker function to process a single document."""
    try:
        # Generate the intelligence profile
        ai_data = generate_ai_profile_with_retry(genai_client, doc_data)
        
        # Write to the subcollection
        subcol_ref = db.collection('mrds_feedstock_profiles').document(doc_id).collection('ai_profiles')
        subcol_ref.add({
            'content': ai_data.get('profile_content', ''),
            'ree_estimate': ai_data.get('ree_estimate', ''),
            'model_used': ai_data.get('model_used', 'Unknown Model'),
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'preloaded': True # Helpful flag to distinguish bulk jobs from live user clicks
        })
        return True, doc_id, None
    except Exception as e:
        return False, doc_id, str(e)

def main():
    print("\n🌍 REEsource - Bulk AI Profile Generator")
    print("------------------------------------------")
    
    db = get_firestore_client()
    genai_client = get_gemini_client()
    
    if not db or not genai_client:
        print("❌ Initialization failed. Check your environment variables.")
        return

    print("🔍 Scanning Firestore for Colorado deposits...")
    
    # 1. Fetch all documents to safely handle multi-state strings
    docs = db.collection('mrds_feedstock_profiles').stream()
    
    work_queue = []
    
    for doc in docs:
        doc_data = doc.to_dict()
        doc_id = doc.id
        
        # Check if it's a Colorado site
        if 'COLORADO' in str(doc_data.get('state', '')).upper():
            # 2. Check if it already has an AI profile
            subcol_ref = db.collection('mrds_feedstock_profiles').document(doc_id).collection('ai_profiles')
            existing_profiles = list(subcol_ref.limit(1).stream())
            
            if not existing_profiles:
                work_queue.append((doc_id, doc_data))

    total_tasks = len(work_queue)
    if total_tasks == 0:
        print("✅ All Colorado deposits already have AI profiles. Nothing to do!")
        return
        
    print(f"🎯 Found {total_tasks} deposits requiring generation.")
    print("🚀 Initiating Gemini 2.5 Flash pipeline with 4 workers...\n")

    success_count = 0
    failure_count = 0
    failures = []

    # 3. Execute Multithreaded Processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Map futures to their specific task data
        future_to_doc = {
            executor.submit(process_single_deposit, db, genai_client, doc_id, data): doc_id 
            for doc_id, data in work_queue
        }
        
        # Use tqdm to create a clean CLI progress bar
        with tqdm(total=total_tasks, desc="Generating Profiles", unit="site") as pbar:
            for future in concurrent.futures.as_completed(future_to_doc):
                success, doc_id, err_msg = future.result()
                
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    failures.append(f"{doc_id}: {err_msg}")
                    
                pbar.update(1)

    # 4. Final Reporting
    print("\n\n📊 --- Execution Summary ---")
    print(f"Total Processed: {total_tasks}")
    print(f"✅ Successful: {success_count}")
    if failure_count > 0:
        print(f"❌ Failed: {failure_count}")
        print("\nFailure Details:")
        for fail in failures:
            print(f" - {fail}")
    else:
        print("\n🎉 All profiles generated and committed to Firestore successfully!")

if __name__ == "__main__":
    main()