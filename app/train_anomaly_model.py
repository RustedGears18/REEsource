import os
import pandas as pd
from sklearn.ensemble import IsolationForest
import time

# --- CONFIGURATION ---
INPUT_PARQUET = os.path.join("data", "processed", "cmb_mid_2023_ml_features.parquet")
OUTPUT_CSV = os.path.join("data", "processed", "cmb_mid_2023_anomalies.csv")

# The percentage of the dataset we expect to be a true anomaly. 
# 0.0005 = 0.05% (Roughly 2,800 pixels out of 5.6 million)
CONTAMINATION_RATE = 0.01

def main():
    print("🧠 Initiating REEsource Anomaly Detection Model...\n" + "="*50)
    
    # 1. LOAD THE MATRIX
    print(f"📥 Loading Parquet Fact Table...")
    start_time = time.time()
    df = pd.read_parquet(INPUT_PARQUET)
    print(f"  -> Loaded {len(df):,} rows in {time.time() - start_time:.2f} seconds.")

    # 2. ISOLATE FEATURES
    # We only feed the scaled numbers to the model, ignoring coordinates for the math
    features = ["eTh_Scaled", "K_Scaled", "RTP_Scaled"]
    X = df[features]

    # 3. TRAIN THE MODEL
    print(f"\n🌲 Training Isolation Forest (Contamination: {CONTAMINATION_RATE*100}%)...")
    model = IsolationForest(
        n_estimators=100,      # Number of decision trees
        contamination=CONTAMINATION_RATE, 
        random_state=42,       # Ensures reproducible results for your capstone defense
        n_jobs=-1              # Uses all available CPU cores
    )
    
    train_start = time.time()
    # Fit the model and predict (-1 means anomaly, 1 means normal)
    df['Anomaly_Label'] = model.fit_predict(X)
    
    # Get the raw anomaly score (lower negative numbers mean MORE anomalous)
    df['Anomaly_Score'] = model.decision_function(X)
    print(f"  -> Training complete in {time.time() - train_start:.2f} seconds.")

    # 4. FILTER AND EXTRACT TARGETS
    print("\n🎯 Extracting high-probability targets...")
    
    # Filter only the rows the model flagged as anomalies (-1)
    anomalies = df[df['Anomaly_Label'] == -1].copy()
    
    # Instead of filtering by the skewed scaler, filter by the raw data.
    # Exclude the 254 background pixels, and keep the highest raw Thorium.
    valid_targets = anomalies[anomalies['eTh_Raw'] < 254].copy()
 
    # Sort by the most extreme anomalies first
    valid_targets = valid_targets.sort_values(by='Anomaly_Score', ascending=True)

    # Optional: Grab the top 500 most extreme points to keep the map snappy
    valid_targets = valid_targets.head(500)

    # 5. SAVE FOR THE DASHBOARD
    print(f"\n💾 Saving targets to {OUTPUT_CSV}...")
    
    # Keep only the essential columns for the map
    output_cols = ["Longitude", "Latitude", "Anomaly_Score", "eTh_Raw", "RTP_Raw"]
    valid_targets[output_cols].to_csv(OUTPUT_CSV, index=False)

    print("="*50)
    print("✅ Model execution successful. Targets are ready for mapping.")

if __name__ == "__main__":
    main()