import os
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import reproject, Resampling
from sklearn.preprocessing import StandardScaler
from dotenv import load_dotenv

# 1. LOAD CREDENTIALS
load_dotenv()

# 2. DEFENSIVE PATH CLEANING
# Extract, strip rogue Windows quotes, and force an absolute path
raw_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
CLEAN_KEY_PATH = os.path.abspath(raw_key_path.strip("'\""))

# 3. PRE-FLIGHT CHECK
if not os.path.exists(CLEAN_KEY_PATH):
    raise FileNotFoundError(
        f"\n❌ GCP Auth Error: Python cannot find the JSON key at:\n{CLEAN_KEY_PATH}\n"
        "Check the path in your .env file."
    )

# Force the clean path back into the OS environment so GDAL inherits it natively
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CLEAN_KEY_PATH

# --- CONFIGURATION ---
GCS_BUCKET = "gs://reesource-earth-mri-rasters/cogs"
OUTPUT_FILE = os.path.join("data", "processed", "cmb_mid_2023_ml_features.parquet")

FEATURE_LAYERS = {
    "eTh": f"{GCS_BUCKET}/Th_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
    "K": f"{GCS_BUCKET}/K_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
    "RTP": f"{GCS_BUCKET}/RTP_AirborneMagneticSurveyColoradoMineralBeltMid2023.tif"
}

def create_coordinate_grid(src):
    """Generates 1D arrays of Latitude and Longitude for every pixel in the master grid."""
    height, width = src.shape
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    # Transform pixel coordinates to geospatial coordinates
    xs, ys = rasterio.transform.xy(src.transform, rows, cols)
    return np.array(xs).flatten(), np.array(ys).flatten()

def fetch_and_align_layer(target_uri, master_src):
    """Streams a raster from GCP and perfectly aligns it to the master grid's coordinate space."""
    # Pass the scrubbed absolute path directly to the C++ engine
    with rasterio.Env(GOOGLE_APPLICATION_CREDENTIALS=CLEAN_KEY_PATH):
        with rasterio.open(target_uri) as src:
            aligned_array = np.empty(master_src.shape, dtype=np.float32)
            
            reproject(
                source=rasterio.band(src, 1),
                destination=aligned_array,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=master_src.transform,
                dst_crs=master_src.crs,
                resampling=Resampling.bilinear
            )
            
            return aligned_array.flatten()

def main():
    print("🚀 Initiating REEsource ML Feature Engineering Pipeline...\n" + "="*50)
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    print("1. Establishing Master Spatial Grid (Using eTh as baseline)...")
    master_uri = FEATURE_LAYERS["eTh"]
    
    # WRAP THE ENTIRE MASTER PROCESS IN THE SECURE ENVIRONMENT
    with rasterio.Env(GOOGLE_APPLICATION_CREDENTIALS=CLEAN_KEY_PATH):
        
        with rasterio.open(master_uri) as master_src:
            lons, lats = create_coordinate_grid(master_src)
            
            master_array = master_src.read(1)
            master_nodata = master_src.nodata
            eth_flat = master_array.flatten()
            
            df = pd.DataFrame({
                "Longitude": lons,
                "Latitude": lats,
                "eTh_Raw": eth_flat
            })
            
            for feature_name, uri in FEATURE_LAYERS.items():
                if feature_name == "eTh": continue 
                print(f"  -> Streaming and co-registering {feature_name} layer...")
                df[f"{feature_name}_Raw"] = fetch_and_align_layer(uri, master_src)

    print("\n2. Cleaning Tabular Matrix...")
    initial_rows = len(df)
    
    if master_nodata is not None:
        df = df[df["eTh_Raw"] != master_nodata]
    
    df = df.dropna()
    
    print(f"  -> Reduced from {initial_rows:,} total pixels to {len(df):,} valid data points.")

    # This ensures the Isolation Forest only evaluates valid geological data.
    df = df[(df['eTh_Raw'] < 254) & (df['K_Raw'] < 254) & (df['RTP_Raw'] < 254)]

    # THEN apply StandardScaler...

    # THEN apply StandardScaler to the remaining valid geological data...

    print("\n3. Normalizing Features for ML Algorithmic distance computation...")
    scaler = StandardScaler()
    
    raw_cols = ["eTh_Raw", "K_Raw", "RTP_Raw"]
    scaled_cols = ["eTh_Scaled", "K_Scaled", "RTP_Scaled"]
    
    df[scaled_cols] = scaler.fit_transform(df[raw_cols])

    print("\n4. Writing highly-optimized Parquet Fact Table...")
    df.to_parquet(OUTPUT_FILE, index=False)
    
    print("="*50)
    print(f"✅ Pipeline Complete! Dataset saved to: {OUTPUT_FILE}")
    print("\nSample of your ML-ready Fact Table:")
    print(df[["Longitude", "Latitude", "eTh_Scaled", "K_Scaled", "RTP_Scaled"]].head())

if __name__ == "__main__":
    main()