import pandas as pd

# Load the fact table
parquet_path = "data/processed/cmb_mid_2023_ml_features.parquet"
df = pd.read_parquet(parquet_path)

# 1. Check the distribution of the Scaled columns
print("📊 Scaled Features Distribution:")
print(df[["eTh_Scaled", "K_Scaled", "RTP_Scaled"]].describe())

# 2. Check the raw values if they exist (to spot the -9999s)
if 'eTh_Raw' in df.columns:
    print("\n🪨 Raw Thorium Distribution:")
    print(df["eTh_Raw"].describe())