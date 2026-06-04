import os
from google.cloud import firestore
from dotenv import load_dotenv

# Load GCP credentials
load_dotenv()

# We will use the same default credentials logic
def get_firestore_client():
    try:
        return firestore.Client()
    except Exception as e:
        print(f"❌ Firestore Auth Error: {e}")
        return None

# The exact URIs from your successful GCS upload
GCS_URIS = [
    "gs://reesource-earth-mri-rasters/surveys/1VD_AirborneMagneticSurveyColoradoMineralBeltMid2023.tif",
    "gs://reesource-earth-mri-rasters/surveys/RTP_AirborneMagneticSurveyColoradoMineralBeltMid2023.tif",
    "gs://reesource-earth-mri-rasters/surveys/K_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
    "gs://reesource-earth-mri-rasters/surveys/Th_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
    "gs://reesource-earth-mri-rasters/surveys/U_AirborneRadiometricSurveyColoradoMineralBeltMid2023.tif",
    "gs://reesource-earth-mri-rasters/surveys/1VD_AirborneMagneticSurveyColoradoMineralBeltNE2024.tif",
    "gs://reesource-earth-mri-rasters/surveys/RTP_AirborneMagneticSurveyColoradoMineralBeltNE2024.tif",
    "gs://reesource-earth-mri-rasters/surveys/K_AirborneRadiometricSurveyColoradoMineralBeltNE2024.tif",
    "gs://reesource-earth-mri-rasters/surveys/Th_AirborneRadiometricSurveyColoradoMineralBeltNE2024.tif",
    "gs://reesource-earth-mri-rasters/surveys/U_AirborneRadiometricSurveyColoradoMineralBeltNE2024.tif",
    "gs://reesource-earth-mri-rasters/surveys/RTPCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif",
    "gs://reesource-earth-mri-rasters/surveys/TMI_IGRFCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif",
    "gs://reesource-earth-mri-rasters/surveys/VDCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24 (1).tif",
    "gs://reesource-earth-mri-rasters/surveys/eThCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif",
    "gs://reesource-earth-mri-rasters/surveys/eUCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif",
    "gs://reesource-earth-mri-rasters/surveys/KCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif",
    "gs://reesource-earth-mri-rasters/surveys/TCCOG_AirborneMagneticAndRadiometricSurveySierraMadreElkheadMedicineBowMountainsRegionWyAndCo2023-24.tif"
]

# --- PARENT SURVEY METADATA ---
# Seeding the parent survey records so our raster assets have a relational anchor
SURVEYS = {
    "cmb_mid_2023": {
        "survey_name": "Colorado Mineral Belt, Mid Block",
        "publication_year": 2023,
        "region": "Colorado"
    },
    "cmb_ne_2024": {
        "survey_name": "Colorado Mineral Belt, NE Block",
        "publication_year": 2024,
        "region": "Colorado"
    },
    "sierra_madre": {
        "survey_name": "Sierra Madre & Medicine Bow Mountains",
        "publication_year": 2024,
        "region": "Wyoming & Colorado"
    }
}

def parse_uri_metadata(uri):
    """Extracts ETL metadata from the raw file naming convention."""
    filename = uri.split('/')[-1]
    
    # 1. Determine Parent Survey
    if "Mid2023" in filename:
        parent_id = "cmb_mid_2023"
    elif "NE2024" in filename:
        parent_id = "cmb_ne_2024"
    elif "SierraMadre" in filename:
        parent_id = "sierra_madre"
    else:
        parent_id = "unknown_survey"

    # 2. Determine Layer Type & Proxy Metric
    filename_upper = filename.upper()
    
    if any(mag in filename_upper for mag in ["1VD", "VDCOG", "RTP", "TMI"]):
        layer_type = "magnetic"
        if "1VD" in filename_upper or "VDCOG" in filename_upper:
            proxy = "1VD"
        elif "RTP" in filename_upper:
            proxy = "RTP"
        else:
            proxy = "TMI"
            
    else:
        layer_type = "radiometric"
        if "ETH" in filename_upper or "TH_" in filename_upper:
            proxy = "eTh"
        elif "EU" in filename_upper or "U_" in filename_upper:
            proxy = "eU"
        elif "K_" in filename_upper or "KCOG" in filename_upper:
            proxy = "K"
        elif "TC" in filename_upper:
            proxy = "Total Count (TC)"
        else:
            proxy = "Unknown Radiometric"

    # Generate a clean document ID (e.g., cmb_mid_2023_eTh)
    doc_id = f"{parent_id}_{proxy}".lower().replace(" ", "_").replace("(", "").replace(")", "")
    
    return doc_id, {
        "parent_survey_id": parent_id,
        "layer_type": layer_type,
        "proxy_metric": proxy,
        "storage_uri": uri,
        "processing_status": "Raw_TIF",
        "original_filename": filename
    }

def main():
    db = get_firestore_client()
    if not db: return

    print("🚀 Initiating REEsource Firestore Seeding...\n" + "="*45)

    # 1. Write the Parent Surveys
    print("Writing parent survey records...")
    for survey_id, data in SURVEYS.items():
        # Using set(merge=True) acts as an upsert, making this script safe to run multiple times
        db.collection("usgs_surveys").document(survey_id).set(data, merge=True)
    print("✅ Parent surveys seeded.")

    # 2. Parse and Write the Raster Assets
    print("\nProcessing raster asset URIs...")
    success_count = 0
    
    for uri in GCS_URIS:
        doc_id, metadata = parse_uri_metadata(uri)
        
        try:
            db.collection("raster_assets").document(doc_id).set(metadata, merge=True)
            print(f"  -> Logged: {doc_id} ({metadata['proxy_metric']})")
            success_count += 1
        except Exception as e:
            print(f"  ❌ Failed to log {doc_id}: {e}")

    print("\n" + "="*45)
    print(f"Database Seeding Complete. {success_count}/{len(GCS_URIS)} assets registered.")

if __name__ == "__main__":
    main()