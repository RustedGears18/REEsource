# REEsource | Critical Mineral Data Pipeline 📈
**Unearthing tomorrow's critical mineral supply.**

## Overview
This repository contains the foundational codebase for an end-to-end Python infrastructure designed to aggregate, analyze, and present Rare Earth Element (REE) feedstock data.

Developed as a Master of Science in Data Analytics capstone project, this application models the viability of localized critical mineral supplies and process parameters. The pipeline provides the data backbone for advanced metallurgical recovery concepts—specifically the processing of acid mine waste and electronic waste using Flash Joule Heating (FJH) and carbochlorination chloride separation. 

## Architecture & Features
* **Interactive Dashboard:** Built with Streamlit, featuring a custom enterprise UI theme.
* **Geological Baselines:** Processes and visualizes assay data targeting High-Density Sludge (HDS) from localized legacy sites.
* **Synthetic Data Governance:** Employs Gaussian Copulas to generate synthetic baseline metrics for regions lacking physical assay data, strictly governing the boundary between physical and generated data.
* **LLM Integration:** Generates dynamic executive summaries of feedstock viability based on queried state parameters.
* **Cloud Caching:** Integrates with Google Cloud Firestore to cache API query profiles (USGS/USMIN) to optimize compute and token overhead.

## Tech Stack
* **Frontend:** Streamlit (`.streamlit/config.toml` customized)
* **Backend:** Python 3.14
* **Database:** Google Cloud Firestore (NoSQL)
* **Environment:** PowerShell 7 / Windows

## Local Development Setup
To run this dashboard locally:

1. Clone the repository:
   ```bash
   git clone [https://github.com/RustedGears18/REEsource.git](https://github.com/RustedGears18/REEsource.git)
   cd REEsource
