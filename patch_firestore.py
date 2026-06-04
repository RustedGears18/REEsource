import os
from google.cloud import firestore
from dotenv import load_dotenv

# 1. LOAD CREDENTIALS
load_dotenv()
raw_key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
CLEAN_KEY_PATH = os.path.abspath(raw_key_path.strip("'\""))

if not os.path.exists(CLEAN_KEY_PATH):
    raise FileNotFoundError(f"\n❌ GCP Auth Error: Cannot find JSON key at: {CLEAN_KEY_PATH}")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CLEAN_KEY_PATH

def main():
    print("🩹 Patching Firestore Metadata Catalog...\n" + "="*50)
    db = firestore.Client()
    
    # The exact files sitting in your GCS surveys/ folder
    missing_assets = [
        {
            "doc_id": "cmb_mid_2023_eth",
            "data": {
                "parent_survey_id": "cmb_mid_2023",
                "layer_type": "radiometric",
                "proxy_metric": "eTh",
                "original_filename": "Th_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "storage_uri": "gs://reesource-earth-mri-rasters/surveys/Th_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "processing_status": "Raw_TIF"
            }
        },
        {
            "doc_id": "cmb_mid_2023_k",
            "data": {
                "parent_survey_id": "cmb_mid_2023",
                "layer_type": "radiometric",
                "proxy_metric": "K",
                "original_filename": "K_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "storage_uri": "gs://reesource-earth-mri-rasters/surveys/K_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "processing_status": "Raw_TIF"
            }
        },
        {
            "doc_id": "cmb_mid_2023_u",
            "data": {
                "parent_survey_id": "cmb_mid_2023",
                "layer_type": "radiometric",
                "proxy_metric": "eU",
                "original_filename": "U_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "storage_uri": "gs://reesource-earth-mri-rasters/surveys/U_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
                "processing_status": "Raw_TIF"
            }
        }
    ]

    for asset in missing_assets:
        doc_ref = db.collection("raster_assets").document(asset["doc_id"])
        doc_ref.set(asset["data"])
        print(f"✅ Injected record for: {asset['data']['proxy_metric']} ({asset['doc_id']})")

    print("="*50)
    print("Patch complete! The database is now synced with the GCS bucket.")

if __name__ == "__main__":
    main()