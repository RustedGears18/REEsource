import os
import logging
from google.oauth2 import service_account
from google.cloud import firestore

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def purge_useless_targets():
    PROJECT_ID = "reesource"
    CREDENTIALS_FILE = "reesource-d2eb4118beff.json"
    COLLECTION_NAME = "ree_targets"
    
    # 1. Authenticate with Firestore
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE)
        db = firestore.Client(credentials=credentials, project=PROJECT_ID)
        logging.info("Authenticated successfully with Firestore.")
    except Exception as e:
        logging.error(f"Authentication failed: {e}")
        return

    # 2. Query for noise cluster IDs
    # HDBSCAN noise is typically -1, sometimes 1 (stored as integers or strings)
    target_noise_ids = [-1, 1, "-1", "1"]
    
    logging.info(f"Scanning '{COLLECTION_NAME}' collection for noise clusters...")
    docs_to_delete = []
    
    # Fetch documents from the collection
    stream = db.collection(COLLECTION_NAME).stream()
    for doc in stream:
        data = doc.to_dict()
        cluster_id = data.get('cluster_id')
        
        if cluster_id in target_noise_ids:
            docs_to_delete.append(doc.reference)

    total_found = len(docs_to_delete)
    if total_found == 0:
        logging.info("No noise documents found. Your collection is clean!")
        return
        
    logging.info(f"Found {total_found} documents marked as noise/useless.")
    
    # 3. Execute Batched Deletions (Max 500 per batch)
    batch = db.batch()
    deletions_in_current_batch = 0
    total_deleted = 0
    
    for doc_ref in docs_to_delete:
        batch.delete(doc_ref)
        deletions_in_current_batch += 1
        total_deleted += 1
        
        # If we hit the 500-operation Firestore limit, commit and open a new batch
        if deletions_in_current_batch == 500:
            logging.info(f"Committing batch of {deletions_in_current_batch} deletions...")
            batch.commit()
            batch = db.batch() # Reset batch
            deletions_in_current_batch = 0
            
    # Commit any remaining items in the final batch
    if deletions_in_current_batch > 0:
        logging.info(f"Committing final batch of {deletions_in_current_batch} deletions...")
        batch.commit()
        
    logging.info(f"✅ Successfully purged {total_deleted} useless documents from '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    # Safety confirmation check before running
    confirm = input("Are you sure you want to permanently delete noise clusters from Firestore? (y/n): ")
    if confirm.lower() == 'y':
        purge_useless_targets()
    else:
        print("Operation cancelled.")