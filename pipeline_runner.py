import gc
import os
import pandas as pd
from google.cloud import storage
from src.config import logging, PROJECT_ID, ACTIVE_DIMENSIONS
from src.ingest import load_and_scale_rasters
from src.cluster import run_grid_search
from src.vectorize import vectorize_clusters
from src.database import push_to_firestore

def main():
    try:
        # 1. Ingest
        valid_df, scaled_data, meta, crs, new_transform, max_area = load_and_scale_rasters()
        
        # 2. Cluster
        best_labels, best_size, best_epsilon, best_score = run_grid_search(scaled_data)
        
        del scaled_data
        gc.collect()
        
        # 3. Vectorize
        gdf = vectorize_clusters(
            valid_df, best_labels, meta, new_transform, max_area, crs, best_size, best_epsilon, best_score
        )
        
        # --- THE DATABASE PROTECTION GATE ---
        # Ensure we have data, sort by the highest z_score, and keep only the top 100
        if not gdf.empty and 'z_score' in gdf.columns:
            logging.info(f"Filtering down from {len(gdf)} total anomalies to the Top 100...")
            gdf = gdf.sort_values(by='z_score', ascending=False).head(100)
            logging.info("✅ Top 100 target threshold applied.")

        # --- ACADEMIC LOGGING INTERCEPT ---
        dimension_string = "_".join(ACTIVE_DIMENSIONS)
        
        # Log the shape to the terminal
        logging.info(f"📊 Final GeoDataFrame Shape for {dimension_string}: {gdf.shape[0]} rows, {gdf.shape[1]} columns")
        
        # Cast to a standard pandas DataFrame to prevent geometry warnings
        sample_df = pd.DataFrame(gdf.head(100).copy())
        
        # Convert polygons to Well-Known Text strings
        sample_df['geometry'] = sample_df['geometry'].apply(lambda x: x.wkt) 
        
        sample_filename = f"target_sample_{dimension_string}.csv"
        sample_df.to_csv(sample_filename, index=False)
        
        # Upload the sample to Cloud Storage
        try:
            storage_client = storage.Client(project=PROJECT_ID)
            bucket = storage_client.bucket("reesource-data-raw")
            blob = bucket.blob(f"outputs/{sample_filename}")
            blob.upload_from_filename(sample_filename)
            logging.info(f"✅ Uploaded 100-row sample to gs://reesource-data-raw/outputs/{sample_filename}")
        except Exception as e:
            logging.error(f"Failed to upload dataframe sample: {e}")
        # ----------------------------------
        
        # 4. Deploy
        push_to_firestore(gdf)
        
        logging.info("Pipeline executed successfully.")
        
    except Exception as e:
        logging.error(f"Pipeline failed: {e}")

if __name__ == '__main__':
    main()