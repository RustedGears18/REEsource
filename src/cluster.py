import hdbscan
import numpy as np
import gc
from src.config import SEARCH_SIZES, SEARCH_EPSILONS, logging

def run_grid_search(scaled_data):
    logging.info("Starting HDBSCAN 2D Auto-Tuning Phase...")
    best_score, best_size, best_epsilon, best_labels = -1.0, None, None, None

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
                if score > best_score:
                    best_score, best_size, best_epsilon, best_labels = score, min_size, current_epsilon, labels
            
            del clusterer, labels
            gc.collect()

    if best_labels is None:
        raise ValueError("Optimization failed to find any valid clusters.")
        
    logging.info(f"Optimization complete. Best: Size {best_size}, Eps {best_epsilon}, DBCV: {best_score:.3f}")
    return best_labels, best_size, best_epsilon
