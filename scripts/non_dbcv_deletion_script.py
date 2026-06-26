import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# 1. Initialize the Firebase Admin SDK
# Replace with the path to your downloaded service account JSON key
cred = credentials.Certificate(r"C:\Users\ryates087\source\repos\REEsource\reesource-d2eb4118beff.json")
firebase_admin.initialize_app(cred)

db = firestore.client()
def cleanup_all_dashboard_targets():
    # The collections used by the Streamlit dashboard
    collections = [
        'target_zones_master',
        'target_zones_U',
        'target_zones_Th',
        'target_zones_K',
        'target_zones_Mag'
    ]
    
    field_to_check = 'dbcv_score'
    batch_size = 400 
    
    for collection_name in collections:
        collection_ref = db.collection(collection_name)
        print(f"\n--- Scanning collection: {collection_name} ---")
        
        docs = collection_ref.stream()
        batch = db.batch()
        
        delete_count = 0
        total_deleted = 0

        for doc in docs:
            doc_data = doc.to_dict()
            
            if field_to_check not in doc_data:
                batch.delete(doc.reference)
                delete_count += 1
                total_deleted += 1

                if delete_count >= batch_size:
                    batch.commit()
                    print(f"Committed batch of {delete_count} deletes. Total deleted: {total_deleted}")
                    batch = db.batch() 
                    delete_count = 0

        if delete_count > 0:
            batch.commit()
            print(f"Committed final batch of {delete_count} deletes. Total deleted: {total_deleted}")

        print(f"Cleanup complete for {collection_name}.")

if __name__ == "__main__":
    cleanup_all_dashboard_targets()