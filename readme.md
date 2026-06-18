# REEsource | Critical Mineral Data Pipeline 📈
**Unearthing tomorrow's critical mineral supply.**

## Overview
REEsource is an end-to-end data analytics and machine learning infrastructure designed to identify, cluster, and model Rare Earth Element (REE) and critical mineral deposits. 

The core machine learning pipeline leverages an optimized HDBSCAN clustering engine running on Google Cloud Platform (GCP) to perform automated geospatial grid searches across multiple geophysical and radiometric dimensions (Uranium, Thorium, Potassium, and Reduced-To-Pole Magnetic density).

## Core Architecture & Features

* **Dynamic Dimensional Slicing:** Accepts runtime environment variables (`ACTIVE_DIMENSIONS`) to execute either the master 4D composite pipeline or individual dimension isolation studies (e.g., Uranium-only anomaly detection) without changing code.
* **Smart Hyperparameter Scaling:** Context-aware hyperparameter engine that automatically rescales HDBSCAN `min_cluster_size` ranges and `cluster_selection_epsilon` boundaries based on the number of input dimensions to counter the Curse of Dimensionality.
* **Automated Data Ingestion:** A resilient Python ETL layer that streams cloud-optimized GeoTIFFs (COGs) from Google Cloud Storage, unpacking and scaling raster arrays efficiently using a multi-gigabyte containerized architecture.
* **Isolated Cloud Database Targets:** Dynamically partitions results into isolated Google Cloud Firestore NoSQL collections based on the active dimensions run (e.g., `target_zones_master` vs `target_zones_U`), preventing database cross-contamination during ablation runs.
* **Interactive Frontend Dashboard:** Built with Streamlit and PyDeck, providing dynamic geospatial vector mapping, interactive filtering, and custom color-palette toggles for different target layers.

## Tech Stack
* **Frontend:** Streamlit, PyDeck, Folium, Leafmap
* **Machine Learning & Geospatial:** Scikit-learn, HDBSCAN, Rasterio, Xarray, NumPy, Pandas
* **Cloud Infrastructure:** Google Cloud Run Jobs, Cloud Build, Cloud Storage, Cloud Firestore
* **Environment & Tools:** Docker (Debian-slim base optimized with GDAL/Expat C-libraries), PowerShell v7, Bash

---

## Production Deployment

### 1. Build and Push Container Image
The container relies on system-level XML and GDAL dependencies to compile `rasterio` successfully. Use Google Cloud Build to compile and tag the production container safely in the cloud registry:

```powershell
gcloud builds submit --tag gcr.io/reesource/pipeline-job
