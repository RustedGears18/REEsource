import os, math
import logging
from dotenv import load_dotenv

# Initialize environment and logging
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

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
NUM_DIMS = len(ACTIVE_DIMENSIONS)

# Dynamically name the output collection
if NUM_DIMS == 4:
    COLLECTION_NAME = "target_zones_master"
else:
    dimension_string = "_".join(ACTIVE_DIMENSIONS)
    COLLECTION_NAME = f"target_zones_{dimension_string}" 

# --- SMART HYPERPARAMETER SCALING ---

# 1. Epsilon Scaling
# Epsilon scales mathematically based on the max Euclidean distance: sqrt(d)
# These base epsilons are tuned for 1D, and scale up as dimensions increase.
base_epsilons = [0.0, 0.15, 0.25, 0.35]
SEARCH_EPSILONS = [round(eps * math.sqrt(NUM_DIMS), 3) for eps in base_epsilons]

# 2. Cluster Size Scaling
# Cluster sizes scale inversely to dimensions. 
# Fewer dimensions = higher density = larger required minimum clusters.
SIZE_SCALER = {
    4: range(20, 45, 5),   # 4D: Highly sparse, small clusters are significant
    3: range(30, 60, 10),  # 3D: Moderate sparsity
    2: range(50, 100, 15), # 2D: Getting dense
    1: range(80, 160, 20)  # 1D: Highly dense, need large numbers to confirm true anomaly
}
SEARCH_SIZES = SIZE_SCALER[NUM_DIMS]
DOWNSAMPLE_FACTOR = 2


