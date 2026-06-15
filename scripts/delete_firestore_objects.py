import sys
import os

# Allow the script to import from the root 'src' directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore
from src.config import PROJECT_ID, COLLECTION_NAME, logging

def delete_collection(batch_size=500):
    logging.info(f"Starting deletion of all documents in collection: {COLLECTION_NAME}")
    db = firestore.Client(project=PROJECT_ID)
    coll_ref = db.collection(COLLECTION_NAME)
    
    deleted_count = 0
    while True:
        docs = list(coll_ref.limit(batch_size).stream())
        if not docs:
            break
            
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        
        batch.commit()
        deleted_count += len(docs)
        logging.info(f"Deleted {deleted_count} documents so far...")
        
    logging.info(f"Successfully purged collection '{COLLECTION_NAME}'. Total deleted: {deleted_count}")

if __name__ == '__main__':
    logging.warning(f"Targeting Project: {PROJECT_ID} | Collection: {COLLECTION_NAME}")
    confirm = input("WARNING: This will delete ALL documents in this collection. Continue? (y/n): ")
    
    if confirm.lower() == 'y':
        delete_collection()
    else:
        logging.info("Operation cancelled by user.")