import hdbscan
import numpy as np
import pandas as pd
import gc
from google.cloud import storage
from src.config import SEARCH_SIZES, SEARCH_EPSILONS, logging, PROJECT_ID

def run_grid_search(scaled_data):
    logging.info("Starting HDBSCAN 2D Auto-Tuning Phase...")
    best_score, best_size, best_epsilon, best_labels = -1.0, None, None, None
    
    # Array to hold the metrics for your capstone paper
    grid_search_history = []

    for min_size in SEARCH_SIZES:
        for current_epsilon in SEARCH_EPSILONS:
            logging.info(f"-> Testing HDBSCAN for min_cluster_size={min_size}, epsilon={current_epsilon}...")
            
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_size, 
                min_samples=15, 
                metric='euclidean', 
                core_dist_n_jobs=6,
                cluster_selection_epsilon=current_epsilon,
                gen_min_span_tree=True  
            )
            
            labels = clusterer.fit_predict(scaled_data)
            
            if np.any(labels != -1):
                score = clusterer.relative_validity_
                logging.info(f"   DBCV Score: {score:.3f}")
                
                grid_search_history.append({
                    'min_cluster_size': min_size,
                    'epsilon': current_epsilon,
                    'dbcv_score': round(score, 4),
                    'valid_clusters_found': len(set(labels)) - (1 if -1 in labels else 0)
                })
                
                if score > best_score:
                    best_score, best_size, best_epsilon, best_labels = score, min_size, current_epsilon, labels
            else:
                logging.info(f"   No target clusters found.")
                grid_search_history.append({
                    'min_cluster_size': min_size,
                    'epsilon': current_epsilon,
                    'dbcv_score': -1.0,
                    'valid_clusters_found': 0
                })
                
            del clusterer, labels
            gc.collect()

    if best_labels is None:
        raise ValueError("Optimization failed to find any valid clusters.")
        
    logging.info(f"Optimization complete. Best: Size {best_size}, Eps {best_epsilon}, DBCV: {best_score:.3f}")
    
    # Save the academic methodology data to GCP
    try:
        history_df = pd.DataFrame(grid_search_history)
        history_df.to_csv("grid_search_history.csv", index=False)
        
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket("reesource-data-raw")
        blob = bucket.blob("outputs/grid_search_history.csv")
        blob.upload_from_filename("grid_search_history.csv")
        logging.info("✅ Uploaded full grid search history to gs://reesource-data-raw/outputs/")
    except Exception as e:
        logging.error(f"Failed to upload grid search history: {e}")

    # Pass the best_score out so it can be injected into Firestore
    return best_labels, best_size, best_epsilon, best_score