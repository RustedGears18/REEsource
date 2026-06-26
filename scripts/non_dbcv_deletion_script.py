import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# 1. Initialize the Firebase Admin SDK
# Replace with the path to your downloaded service account JSON key
cred = credentials.Certificate(r"C:\Users\ryates087\source\repos\REEsource\reesource-d2eb4118beff.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

def cleanup_ree_targets():
    collection_ref = db.collection('ree_targets')
    field_to_check = 'dbcv_score'
    batch_size = 400 # Firestore limits batches to 500 operations
    
    print(f"Scanning collection for missing '{field_to_check}' fields...")
    
    # Use stream() for memory-efficient reading
    docs = collection_ref.stream()
    batch = db.batch()
    
    delete_count = 0
    total_deleted = 0

    for doc in docs:
        doc_data = doc.to_dict()
        
        # Check if the field is missing
        if field_to_check not in doc_data:
            batch.delete(doc.reference)
            delete_count += 1
            total_deleted += 1

            # Commit the batch when it reaches the limit
            if delete_count >= batch_size:
                batch.commit()
                print(f"Committed batch of {delete_count} deletes. Total deleted: {total_deleted}")
                batch = db.batch() # Reset batch
                delete_count = 0

    # Commit any remaining operations in the final batch
    if delete_count > 0:
        batch.commit()
        print(f"Committed final batch of {delete_count} deletes. Total deleted: {total_deleted}")

    print("Cleanup complete.")

if __name__ == "__main__":
    cleanup_ree_targets()