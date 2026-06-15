import os
from dotenv import load_dotenv
from google.cloud import firestore

# Load environment variables
load_dotenv()

# Initialize Firestore Client
db = firestore.Client()

def cleanup_missing_epsilon():
    collection_ref = db.collection('ree_targets')
    docs = collection_ref.stream()
    
    batch = db.batch()
    batch_size = 0
    total_deleted = 0
    
    for doc in docs:
        # Check if 'epsilon' field is missing
        if 'epsilon' not in doc.to_dict():
            batch.delete(doc.reference)
            batch_size += 1
            total_deleted += 1
            
            # Firestore batches are limited to 500 operations
            if batch_size >= 500:
                batch.commit()
                print(f"Committed batch of {batch_size} deletions.")
                batch = db.batch()
                batch_size = 0
    
    # Commit any remaining deletions
    if batch_size > 0:
        batch.commit()
        print(f"Committed final batch of {batch_size} deletions.")
        
    print(f"Cleanup complete. Total documents deleted: {total_deleted}")

if __name__ == "__main__":
    cleanup_missing_epsilon()