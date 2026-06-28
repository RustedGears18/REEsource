import hdbscan
import numpy as np
import pandas as pd
import gc
from google.cloud import storage
from src.config import SEARCH_SIZES, SEARCH_EPSILONS, NUM_DIMS, logging, PROJECT_ID

def run_grid_search(scaled_data):
    logging.info("Starting HDBSCAN Autonomous Auto-Tuning Phase...")
    
    TARGET_DBCV = 0.80 if NUM_DIMS == 4 else 0.50
    ABSOLUTE_MIN_DBCV = 0.75 if NUM_DIMS == 4 else 0.30
    
    MAX_RETRIES = 3
    
    # Isolate parameters so we can mutate them during retries
    current_sizes = list(SEARCH_SIZES)
    current_epsilons = list(SEARCH_EPSILONS)
    
    global_best_score = -1.0
    global_best_size, global_best_eps, global_best_labels = None, None, None
    grid_search_history = []
    
    attempt = 0
    threshold_met = False

    # The Recursive Smart-Scaling Loop
    while attempt < MAX_RETRIES and not threshold_met:
        logging.info(f"--- Iteration {attempt + 1}/{MAX_RETRIES} ---")
        logging.info(f"Testing Sizes: {current_sizes}")
        logging.info(f"Testing Epsilons: {current_epsilons}")
        
        iteration_best_score = -1.0
        
        for min_size in current_sizes:
            
            # Dynamically scale min_samples to prevent core distance conflicts
            # Keeps samples at exactly 50% of the cluster size, but never drops below 5
            dynamic_min_samples = max(5, min_size // 2)
            
            for current_epsilon in current_epsilons:
                
                clusterer = hdbscan.HDBSCAN(
                    min_cluster_size=min_size, 
                    min_samples=dynamic_min_samples,   # <-- Dynamic injection
                    metric='euclidean', 
                    core_dist_n_jobs=6,
                    cluster_selection_epsilon=current_epsilon,
                    gen_min_span_tree=True  
                )
                
                labels = clusterer.fit_predict(scaled_data)
                
                if np.any(labels != -1):
                    score = clusterer.relative_validity_
                    
                    grid_search_history.append({
                        'attempt_tier': attempt + 1,
                        'min_cluster_size': min_size,
                        'epsilon': current_epsilon,
                        'dbcv_score': round(score, 4),
                        'valid_clusters_found': len(set(labels)) - (1 if -1 in labels else 0)
                    })
                    
                    # Track the best score globally across all iterations
                    if score > global_best_score:
                        global_best_score = score
                        global_best_size = min_size
                        global_best_eps = current_epsilon
                        global_best_labels = labels
                        
                    # Track the best score for this specific iteration block
                    if score > iteration_best_score:
                        iteration_best_score = score
                else:
                    grid_search_history.append({
                        'attempt_tier': attempt + 1,
                        'min_cluster_size': min_size,
                        'epsilon': current_epsilon,
                        'dbcv_score': -1.0,
                        'valid_clusters_found': 0
                    })
                        
                del clusterer, labels
                gc.collect()

        # Evaluate if we hit our target threshold
        if global_best_score >= TARGET_DBCV:
            logging.info(f"✅ Target DBCV ({TARGET_DBCV}) achieved with {global_best_score:.3f}")
            threshold_met = True
        else:
            logging.warning(f"⚠️ Max DBCV was {iteration_best_score:.3f} (Target: {TARGET_DBCV}).")
            attempt += 1
            
            if attempt < MAX_RETRIES:
                logging.info("Initiating Smart Fallback: Increasing geospatial granularity...")
                # Reduce sizes by 25% to force the algorithm to look for smaller anomalies
                current_sizes = [max(10, int(s * 0.75)) for s in current_sizes]
                # Tighten epsilon by 20% to demand denser clusters
                current_epsilons = [round(e * 0.8, 3) for e in current_epsilons]

    # --- End of while loop ---

    if global_best_labels is None:
        raise ValueError("Total optimization failure: No valid clusters found across all retry tiers.")
        
    if not threshold_met:
        logging.warning(f"Reached max retries ({MAX_RETRIES}). Best DBCV was: {global_best_score:.3f}")
        
        # --- THE HARD CUTOFF QC GATE ---
        if global_best_score < ABSOLUTE_MIN_DBCV:
            logging.error(f"❌ QC FAILURE: Best DBCV ({global_best_score:.3f}) fell below the absolute floor of {ABSOLUTE_MIN_DBCV}.")
            raise ValueError("Quality Control Rejection: All discovered clusters are statistical noise.")
        else:
            logging.info(f"⚠️ Best DBCV ({global_best_score:.3f}) is below ideal target, but above the absolute floor. Proceeding.")
        
    logging.info(f"Final Selection -> Size: {global_best_size}, Eps: {global_best_eps}, DBCV: {global_best_score:.3f}")
    
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

    return global_best_labels, global_best_size, global_best_eps, global_best_score