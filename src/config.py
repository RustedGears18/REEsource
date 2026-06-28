import os, math
import logging
from dotenv import load_dotenv
from datetime import datetime, timezone

# Initialize environment and logging
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Generate a single UTC timestamp for the entire pipeline execution
RUN_TIMESTAMP = datetime.now(timezone.utc).isoformat()

# GCP & Database Setup
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reesource")
COLLECTION_NAME = 'ree_targets'

# Data Paths
FILE_PATHS = {
    'U': 'gs://reesource-data-raw/surveys/raw_tifs/CO_MID_u.tif',
    'Th': 'gs://reesource-data-raw/surveys/raw_tifs/CO_MID_th.tif',
    'K': 'gs://reesource-data-raw/surveys/raw_tifs/CO_MID_k.tif',
    'Mag': 'gs://reesource-data-raw/surveys/raw_tifs/CO_MID_rtp.tif'
}

# Catch the execution parameter, defaulting to the full 4D stack
ACTIVE_DIMENSIONS = os.getenv("ACTIVE_DIMENSIONS", "U,Th,K,Mag").split(",")
DOWNSAMPLE_FACTOR=2
NUM_DIMS = len(ACTIVE_DIMENSIONS)

# Catch the survey provenance tag
SURVEY_SOURCE = os.getenv("SURVEY_SOURCE", "USGS_Earth_MRI_CO_MID_MINERAL_BELT")

# Dynamically name the output collection
if NUM_DIMS == 4:
    COLLECTION_NAME = "target_zones_master"
else:
    dimension_string = "_".join(ACTIVE_DIMENSIONS)
    COLLECTION_NAME = f"target_zones_{dimension_string}" 

# Force higher epsilons to merge nearby tiny clusters together
base_epsilons = [0.0, 0.3, 0.5, 0.7, 0.9] 

# Drastically increase the minimum pixel sizes----test
SIZE_SCALER = {
    4: range(10, 20, 5), 
    3: range(20, 30, 5),
    2: range(30, 40 ,5),
    1: range(40, 50, 5)
}

# Check for runtime environment variable overrides
custom_sizes = os.getenv("CUSTOM_SIZES")
custom_epsilons = os.getenv("CUSTOM_EPSILONS")

if custom_sizes:
    # Parse comma-separated string into a list of integers
    SEARCH_SIZES = [int(x.strip()) for x in custom_sizes.split(",")]
else:
    SEARCH_SIZES = SIZE_SCALER[NUM_DIMS]

if custom_epsilons:
    # Parse comma-separated string into a list of floats
    SEARCH_EPSILONS = [float(x.strip()) for x in custom_epsilons.split(",")]
else:
    SEARCH_EPSILONS = [round(eps * math.sqrt(NUM_DIMS), 3) for eps in base_epsilons]

