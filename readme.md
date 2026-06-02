# REEsource | Critical Mineral Data Pipeline 📈
**Unearthing tomorrow's critical mineral supply.**

## Overview
This repository contains the foundational codebase for an end-to-end Python infrastructure designed to aggregate, analyze, and present Rare Earth Element (REE) and critical mineral feedstock data.

Designed for researchers, developers, and business operators, this application models the viability of critical mineral supplies across the United States, defaulting to a strict REE profile while allowing exploration of all critical minerals. 

## Architecture & Features
* **Interactive Dashboard:** Built with Streamlit, featuring dynamic geospatial mapping and a default UI toggle prioritizing REE filtering.
* **Geological Baselines:** Processes and visualizes assay data targeting critical mineral deposits from legacy and active sites nationwide.
* **Self-Healing References:** Implements dynamic query-generation to Mindat.org to prevent link-rot on legacy federal datasets, ensuring continuous access to deposit intelligence.
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
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows
   .\.venv\Scripts\Activate.ps1
   # macOS/Linux
   source .venv/bin/activate
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set up your environment variables:
   * Create a `.env` file in the root directory.
   * Add your Google Cloud service account JSON path: `GOOGLE_APPLICATION_CREDENTIALS="path/to/your/key.json"`
5. Run the application:
   ```bash
   streamlit run dashboard.py
   ```