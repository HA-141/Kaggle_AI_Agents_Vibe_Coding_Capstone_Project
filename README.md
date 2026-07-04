# MedTech Stock Analyst

## Overview
This repository implements a **multi‑agent system** using the **Agent Development Kit (ADK)** to predict and explain stock price movements for five med‑tech, biotech, and pharma companies (JNJ, NVO, PFE, AMGN, GSK).  Agents independently gather publicly available data (clinical trials, CMS prescriber data, PubMed, USAspending, GDELT) and a price data source, combine their signals with an Ensemble agent, and produce a human‑readable report.

## Architecture
- **Orchestrator Agent** – entry point; validates inputs, dispatches six agents in parallel, forwards results to the Ensemble and Report‑Writer.
- **Indicator Agents** (5) – each wraps a dedicated MCP server that fetches and processes a specific data source.  All agents return a **standard JSON schema**.
- **Price Data Agent** – provides historical price series and forward return for back‑testing.
- **Ensemble / Ranking Agent** – weighted aggregation of indicator signals, identifies mainstream vs. under‑covered signals.
- **Report‑Writer Agent** – formats the ensemble output into a concise narrative with citations.
- **MCP Servers** – lightweight wrappers around public APIs (ClinicalTrials.gov, CMS Prescriber PUF, PubMed E‑utilities, USAspending, GDELT, yfinance).  No API keys are hard‑coded; values are read from `.env`.
- **Back‑test Runner** – orchestrates historical runs, enforces look‑ahead‑bias limits, scores predictions.
- **Frontend** – vanilla HTML/JS UI allowing the user to select a ticker, mode (live/backtest), and an optional date for back‑testing.  Results are displayed with the prediction and a breakdown of contributing indicators.

## Setup
1. **Clone the repo**
   ```bash
   git clone <repo‑url>
   cd Kaggle-AI-Agents-MedTech-Stock-Analyst
   ```
2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```
3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Fill in any needed API keys (e.g., FDA, USAspending) – most data sources are public.
   ```
5. **Start MCP servers** (each runs in its own process; a helper script is provided)
   ```bash
   python -m mcp_servers.run_all
   ```
6. **Run the backend** (a tiny FastAPI wrapper that launches the Orchestrator)
   ```bash
   uvicorn backend:app --reload
   ```
7. **Open the frontend** – navigate to `frontend/index.html` in a browser (or use the dev server that ships with the FastAPI static files).

## Usage
### Live Mode
- Choose a ticker, set mode to **Live**, and click **Run**.
- The system fetches the latest data, produces a prediction, and displays the report.

### Back‑test Mode
- Select a ticker, set mode to **Backtest**, and provide an **as‑of date** (YYYY‑MM‑DD).
- The runner filters each data source by its real‑world release lag (e.g., CMS data 18‑24 months) so that only information available on that date is used.
- After the prediction is generated, the forward return (price change over the next N trading days) is fetched and the result is scored.
- The UI shows the prediction, the back‑tested forward return, and the accuracy summary.

## Project Structure
```
Kaggle-AI-Agents-MedTech-Stock-Analyst/
├─ agents/
│   ├─ orchestrator/
│   ├─ indicators/
│   │   ├─ clinical_trials_agent.py
│   │   ├─ physician_adoption_agent.py
│   │   ├─ pubmed_agent.py
│   │   ├─ usaspending_agent.py
│   │   └─ gdelt_agent.py
│   ├─ price_data/
│   ├─ ensemble_ranking/
│   └─ report_writer/
├─ mcp_servers/
│   ├─ clinical_trials.py
│   ├─ cms_prescriber.py
│   ├─ pubmed.py
│   ├─ usaspending.py
│   ├─ gdelt.py
│   └─ price_data.py
├─ backtest/runner.py
├─ frontend/
│   ├─ index.html
│   └─ static/
│       ├─ style.css
│       └─ app.js
├─ utils/
│   └─ mcp_tools.py
├─ .env.example
├─ requirements.txt
├─ README.md
└─ DEVELOPER_GUIDE.md
```

## Contributing
Feel free to open issues or PRs.  When adding a new indicator, follow the same schema and update the orchestrator’s dispatch list.

---
*This README is designed for a public GitHub repository.*
