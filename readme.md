# REEsource | Critical Mineral Data Pipeline 📈

**Unearthing tomorrow's critical mineral supply.**

## Overview
This repository contains the foundational codebase for an end-to-end Python infrastructure designed to aggregate, analyze, and present Rare Earth Element (REE) feedstock data. 

Developed as the capstone project for the MS in Data Analytics program at Colorado State University Global, this application models the viability of localized critical mineral supplies and process parameters.

## Architecture & Features
* **Interactive Dashboard:** Built with Streamlit, featuring a custom enterprise UI theme.
* **Geological Baselines:** Processes and visualizes assay data targeting High-Density Sludge (HDS) from localized legacy sites (e.g., Argo Tunnel, North Clear Creek).
* **Synthetic Data Governance:** Employs Gaussian Copulas to generate synthetic baseline metrics for regions lacking physical assay data, strictly governing the boundary between physical and generated data.
* **LLM Integration:** Generates dynamic executive summaries of feedstock viability based on queried state parameters.
* **Cloud Caching:** Integrates with Google Cloud Firestore to cache API query profiles (USGS/USMIN) to optimize compute and token overhead.

## Tech Stack
* **Frontend:** Streamlit (`.streamlit/config.toml` customized)
* **Backend:** Python 3.x
* **Database:** Google Cloud Firestore (NoSQL)
* **Environment:** PowerShell 7 / Windows

## Local Development Setup
To run this dashboard locally:

1. Clone the repository.
2. Ensure you have Python installed and create a virtual environment (`.venv`).
3. Install the required dependencies:
      streamlit