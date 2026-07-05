# MedTech Stock Analyst

A multi-agent AI system that predicts short-term stock movements for five healthcare companies (JNJ, NVO, PFE, AMGN, GSK) by analysing clinical trials, Medicare prescriber data, PubMed publications, government contracts, and news sentiment.

## Quick-Start

1. **Clone and enter the repo**
   ```
   git clone <repo-url>
   cd Kaggle-AI-Agents-MedTech-Stock-Analyst
   ```

2. **Create a virtual environment** (Python 3.11+)
   ```
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   source .venv/bin/activate     # macOS / Linux
   ```

3. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

4. **Set up API keys** — copy and fill in the environment file (see [API Keys & Configuration](#api-keys--configuration)):
   ```
   cp .env.example .env
   ```
   Edit `.env` with your Gemini API key (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)). Without it, the LLM agents cannot run.

   > **Frontend key entry:** You can also enter your API key directly in the browser UI — see the settings panel at the top of the page. Keys entered in the browser are stored only in that session and never sent anywhere except to the Gemini API.

5. **Start the backend server**
   ```
   python frontend/server.py
   ```

6. **Open the UI** at [http://localhost:8000](http://localhost:8000), select a company and click **Run Analysis**.

## Architecture Overview

- **Orchestrator** — entry point that dispatches all 6 agents in parallel, collects results, and passes them to the ensemble and report writer.
- **5 Indicator Agents** — each wraps an MCP server that calls a public data source (ClinicalTrials.gov, CMS Prescriber PUF, PubMed, USAspending.gov, GDELT). All return the same standardised JSON schema.
- **Price Data Agent** — fetches historical OHLCV prices from yfinance. In backtest mode, data is strictly capped at the as-of date.
- **Ensemble / Ranking Agent** — a pure-reasoning LLM agent that weighs the five indicator signals by confidence, ranks them, and tags each as mainstream (priced in) vs. under-covered (leading signal).
- **Report Writer Agent** — formats the ensemble output into a readable markdown report with source citations and a disclaimer.
- **Backtest Runner** — runs historical predictions, enforces release-lag lookahead filtering for each data source, then scores predictions against actual forward returns.

For full technical detail (schema definitions, MCP server internals, lookahead-bias table, adding indicators), see [ARCHITECTURE.md](ARCHITECTURE.md).

## API Keys & Configuration

The project requires one credential to run:

| Variable | Used by | How to get |
|---|---|---|
| `GEMINI_API_KEY` | All LLM agents (via Google ADK) | Free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GOOGLE_GENAI_USE_VERTEXAI` | (alternative auth) | Set to `True` if using Vertex AI instead |

All variables go in `.env` at the project root (copy from `.env.example`). The `.env` file is listed in `.gitignore` — **never commit it**.

All data-source MCP servers (ClinicalTrials.gov, CMS, PubMed, USAspending.gov, GDELT, yfinance) are free and require no API keys.

**Frontend key entry:** If you are using the deployed public demo or just visiting the repo, you can enter your `GEMINI_API_KEY` directly in the browser settings panel (click the gear icon). The key is stored only in your browser session (in-memory), never persisted, and used only for the Gemini API calls.

## Usage

### Live mode
Select a ticker, set mode to **Live**, click **Run**. The system fetches the latest data and produces a prediction.

### Backtest mode
Select a ticker, set mode to **Backtest**, provide an as-of date (YYYY-MM-DD). Each data source is filtered by its real-world release lag so only information available on that date is used. After the prediction is generated, the forward return is fetched and the result is scored.

### CLI (without browser)
```bash
# Live
python -m agents.orchestrator.orchestrator --ticker JNJ --mode live

# Backtest
python -m agents.orchestrator.orchestrator --ticker NVO --mode backtest --date 2023-06-01

# Backtest runner with scoring
python -m backtest.runner --pairs JNJ:2023-01-15 PFE:2023-09-01
```

## Deployment

The app runs on any machine with Python. For public deployment, the recommended approach is Google Cloud Run (see [ARCHITECTURE.md](ARCHITECTURE.md) for the Dockerfile). A live demo — when deployed — will be linked here.

## Limitations & Future Work

- **LLM dependency:** The ensemble and report-writer agents require a Gemini API call. Without one (or without Vertex AI), the system degrades to neutral fallbacks.
- **Simplified lag model:** Release lags are implemented as fixed constants (e.g., CMS 21 months, PubMed 14 days). Real-world data availability can vary.
- **Five-company universe:** Only JNJ, NVO, PFE, AMGN, GSK are supported. Adding tickers requires updating MCP server mappings and orchestrator validation.
- **Indicators not yet built:** Regulatory approval tracking, patent cliff monitoring, and earnings-call sentiment are scoped out.
- **Backtest scoring is directional:** The magnitude hit/miss comparison uses the ensemble's plain-text range, which is approximate.
- **No authentication on the web UI:** The frontend is unprotected — suitable for demos and local use only.

---

*For detailed schema definitions, MCP server documentation, indicator-addition guide, and common errors, see [ARCHITECTURE.md](ARCHITECTURE.md).*
