import os
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

# Hyperparameters
SEARCH_SIZES = range(20, 45, 5) 
SEARCH_EPSILONS = [0.0, 0.3, 0.5, 0.7]  
DOWNSAMPLE_FACTOR = 2
