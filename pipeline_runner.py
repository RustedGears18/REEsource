import gc
from src.config import logging
from src.ingest import load_and_scale_rasters
from src.cluster import run_grid_search
from src.vectorize import vectorize_clusters
from src.database import push_to_firestore

def main():
    try:
        # 1. Ingest
        valid_df, scaled_data, meta, crs, new_transform, max_area = load_and_scale_rasters()
        
        # 2. Cluster (Now capturing the best_score)
        best_labels, best_size, best_epsilon, best_score = run_grid_search(scaled_data)
        
        del scaled_data
        gc.collect()
        
        # 3. Vectorize (Passing the best_score in)
        gdf = vectorize_clusters(
            valid_df, best_labels, meta, new_transform, max_area, crs, best_size, best_epsilon, best_score
        )
        
        # 4. Deploy
        push_to_firestore(gdf)
        
        logging.info("Pipeline executed successfully.")
        
    except Exception as e:
        logging.error(f"Pipeline failed: {e}")

if __name__ == '__main__':
    main()