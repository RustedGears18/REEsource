import os
import json
import time
import logging
from datetime import datetime
import concurrent.futures
from google.cloud import firestore
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tqdm import tqdm

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
    target_model = 'gemini-2.5-flash'
    
    prompt = f"""
    You are an expert geological research librarian and data custodian. 
    Create a site profile for the '{deposit_data['deposit_name']}' deposit in {deposit_data['state']}.
    
    Strict Execution Guidelines:
    1. Length: Limit your description to a maximum of 1000 words, but be concise if the provided data is sparse. Do not add conversational fluff.
    2. Focus: Synthesize the provided 'Available Site Context' to explain the formation and extraction methods associated with this deposit.
    3. Exclusions: Do NOT include sections on "Recent Developments" or "Environmental Issues". 
    4. CITATION RULE: Do NOT generate a bibliography, do not invent citations, and do not hallucinate external URLs. The ONLY source you may reference is the USGS MRDS data point URI: {deposit_data.get('source_link', 'N/A')}
    5. Discovery: Generate 3 to 5 highly specific keyword search strategies (Google Dorks) to help a human researcher find real unstructured ICP-MS assay data or REE concentrations for this site online (e.g., `"Deposit Name" AND ("ICP-MS" OR "rare earth") filetype:pdf`).
    
    CRITICAL OUTPUT FORMAT:
    You must return your ENTIRE response as a valid JSON object matching this structure exactly:
    {{
        "profile_content": "<The markdown formatted summary of the site.>",
        "ree_estimate": "<A 2-3 sentence estimation of REE potential based on the provided mineralogy.>",
        "search_strategies": [
            {{
                "query": "<The optimized Google Dork>",
                "rationale": "<Brief explanation of why this query is useful>"
            }}
        ]
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
            response = client.models.generate_content(
                model=target_model, 
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            parsed_json = json.loads(response.text)
            parsed_json['model_used'] = target_model
            return parsed_json
        except Exception as e:
            if attempt == max_retries - 1:
                raise Exception(f"Failed after {max_retries} attempts. Last error: {e}")
            time.sleep(2 ** attempt) 

def process_single_deposit(db, genai_client, doc_id, doc_data):
    try:
        ai_data = generate_ai_profile_with_retry(genai_client, doc_data)
        subcol_ref = db.collection('mrds_feedstock_profiles').document(doc_id).collection('ai_profiles')
        subcol_ref.add({
            'content': ai_data.get('profile_content', ''),
            'ree_estimate': ai_data.get('ree_estimate', ''),
            'search_strategies': ai_data.get('search_strategies', []),
            'model_used': ai_data.get('model_used', 'Unknown Model'),
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'preloaded': True 
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
        print("❌ Initialization failed.")
        return

    print("🔍 Scanning Firestore for Colorado deposits...")
    docs = db.collection('mrds_feedstock_profiles').stream()
    work_queue = []
    
    for doc in docs:
        doc_data = doc.to_dict()
        doc_id = doc.id
        if 'COLORADO' in str(doc_data.get('state', '')).upper():
            subcol_ref = db.collection('mrds_feedstock_profiles').document(doc_id).collection('ai_profiles')
            existing_profiles = list(subcol_ref.limit(1).stream())
            if not existing_profiles:
                work_queue.append((doc_id, doc_data))

    total_tasks = len(work_queue)
    if total_tasks == 0:
        print("✅ All targeted deposits already have AI profiles.")
        return
        
    print(f"🎯 Found {total_tasks} deposits requiring generation.")
    
    success_count = 0
    failure_count = 0
    failures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_doc = {
            executor.submit(process_single_deposit, db, genai_client, doc_id, data): doc_id 
            for doc_id, data in work_queue
        }
        with tqdm(total=total_tasks, desc="Generating Profiles", unit="site") as pbar:
            for future in concurrent.futures.as_completed(future_to_doc):
                success, doc_id, err_msg = future.result()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    failures.append(f"{doc_id}: {err_msg}")
                pbar.update(1)

    print("\n\n📊 --- Execution Summary ---")
    print(f"Total Processed: {total_tasks}")
    print(f"✅ Successful: {success_count}")
    if failure_count > 0:
        print(f"❌ Failed: {failure_count}")
        for fail in failures:
            print(f" - {fail}")

if __name__ == "__main__":
    main()