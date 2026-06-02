# REEsource | Critical Mineral Data Pipeline 📈
**Unearthing tomorrow's critical mineral supply.**

## Overview
This repository contains the foundational codebase for an end-to-end Python infrastructure designed to aggregate, analyze, and present Rare Earth Element (REE) and critical mineral feedstock data.

Designed for researchers, developers, and business operators, this application models the viability of critical mineral supplies across the United States. It provides a robust data backbone for supply chain analysis, geological research, and resource management.

## Architecture & Features
* **Interactive Dashboard:** Built with Streamlit, featuring a custom enterprise UI theme and dynamic geospatial mapping.
* **Geological Baselines:** Processes and visualizes assay data targeting critical mineral deposits from legacy and active sites nationwide.
* **Automated Data Ingestion:** A resilient Python ETL pipeline that dynamically resolves, downloads, and transforms the latest federal dataset from the USGS/Data.gov catalog.
* **Cloud Database:** Integrates with Google Cloud Firestore (NoSQL) to cache and serve processed tracking records seamlessly to the frontend.

## Tech Stack
* **Frontend:** Streamlit (`.streamlit/config.toml` customized), Folium
* **Backend:** Python 3.x, Pandas, Requests
* **Database:** Google Cloud Firestore
* **Environment:** Compatible with Windows/PowerShell, macOS, and Linux

## Local Development Setup
To run this dashboard locally:

1. Clone the repository:
   ```bash
   git clone [https://github.com/RustedGears18/REEsource.git](https://github.com/RustedGears18/REEsource.git)
   cd REEsource
   
2. Create the virtual environment
Create and activate a virtual environment:
```bash
python -m venv .venv
```Windows
.\.venv\Scripts\Activate.ps1
```macOS/Linux
source .venv/bin/activate

3. Install the required dependencies
Install the required dependencies:

```Bash
pip install -r requirements.txt
Set up your environment variables:

Create a .env file in the root directory.

Add your Google Cloud service account JSON path: GOOGLE_APPLICATION_CREDENTIALS="path/to/your/key.json"

Run the application:

```Bash
streamlit run dashboard.py```

