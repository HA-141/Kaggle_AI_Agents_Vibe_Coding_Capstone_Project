# Developer Guide — MedTech Stock Analyst

> Last updated: July 2026  
> Audience: engineers contributing to or deploying the system

---

## Table of Contents

1. [Overview](#1-overview)  
2. [Repository Structure](#2-repository-structure)  
3. [Environment Setup](#3-environment-setup)  
4. [Running Without the Frontend (CLI)](#4-running-without-the-frontend-cli)  
5. [Running the Web Frontend](#5-running-the-web-frontend)  
6. [How Each Component Works](#6-how-each-component-works)  
   - 6.1 MCP Servers  
   - 6.2 Indicator Agents  
   - 6.3 Price Data Agent  
   - 6.4 Ensemble Agent  
   - 6.5 Report Writer Agent  
   - 6.6 Orchestrator  
   - 6.7 Backtest Runner  
7. [Data Sources & Lookahead Bias](#7-data-sources--lookahead-bias)  
8. [Adding a New Indicator](#8-adding-a-new-indicator)  
9. [Testing & Validation](#9-testing--validation)  
10. [Deployment](#10-deployment)  
11. [Common Errors](#11-common-errors)

---

## 1. Overview

The MedTech Stock Analyst is a multi-agent AI system that predicts and explains short-term stock price movements for five healthcare companies (JNJ, NVO, PFE, AMGN, GSK). It is built with:

- **Google Agent Development Kit (ADK)** — agent framework, tool calling, InMemoryRunner
- **Model Context Protocol (MCP)** — standardised, stdio-based tool interface for each data source
- **Gemini 2.5 Flash / Pro** (via Vertex AI or AI Studio) — LLM for all agents
- **FastAPI** — REST API backend serving the browser UI
- **yfinance** — price data (live and historical)

### Execution Flow

```
User Request (CLI or Browser)
          │
          ▼
   Orchestrator Agent
          │
    ┌─────┴──────────────────────────────────────┐
    │ asyncio.gather() — all 6 agents in parallel │
    └──┬──────┬──────┬──────┬──────┬─────────────┘
       │      │      │      │      │
  Clinical  Phys.  PubMed  USA   GDELT   Price
  Trials   Adopt.        Spend. Senti.   Data
  Agent    Agent  Agent   Agent  Agent   Agent
       │      │      │      │      │
   (MCP call per agent, date-capped)
          │
          ▼
   Ensemble Agent (weighted rank → signal + confidence)
          │
          ▼
   Report Writer Agent (markdown narrative)
          │
          ▼
     Structured JSON result
```

---

## 2. Repository Structure

```
Kaggle-AI-Agents-MedTech-Stock-Analyst/
│
├── agents/
│   ├── __init__.py
│   ├── schemas.py                  # Pydantic schemas (IndicatorOutput, EnsembleOutput …)
│   ├── mcp_tools.py                # Helper: call an MCP server over stdio
│   │
│   ├── indicators/                 # Five indicator agents
│   │   ├── clinical_trials_agent.py
│   │   ├── physician_adoption_agent.py
│   │   ├── pubmed_agent.py
│   │   ├── usaspending_agent.py
│   │   └── gdelt_agent.py
│   │
│   ├── price_data/
│   │   └── price_data_agent.py     # Fetches OHLCV data + forward returns
│   │
│   ├── ensemble_ranking/
│   │   └── ensemble_agent.py       # Weighted signal aggregation
│   │
│   ├── report_writer/
│   │   └── report_writer_agent.py  # Human-readable markdown narrative
│   │
│   └── orchestrator/
│       └── orchestrator.py         # Parallel coordination + CLI entry point
│
├── mcp_servers/                    # Each server is a standalone Python MCP server
│   ├── clinical_trials.py          # ClinicalTrials.gov REST API
│   ├── cms_prescriber.py           # CMS Medicare Part D Prescriber PUF
│   ├── pubmed.py                   # NCBI PubMed E-utilities
│   ├── usaspending.py              # USAspending.gov API
│   ├── gdelt.py                    # GDELT GKG news API
│   └── price_data.py               # yfinance (OHLCV)
│
├── backtest/
│   └── runner.py                   # Dated backtest + scoring CLI
│
├── frontend/
│   ├── server.py                   # FastAPI app + /api/predict endpoint
│   └── static/
│       ├── index.html              # Browser UI (glassmorphism dark theme)
│       ├── style.css
│       └── app.js
│
├── .env                            # Local secrets (not committed)
├── .env.example                    # Template with documentation
├── .gitignore
├── requirements.txt
├── README.md
└── DEVELOPER_GUIDE.md              # This file
```

---

## 3. Environment Setup

### 3.1 Prerequisites

| Tool | Minimum version |
|------|----------------|
| Python | 3.11 |
| pip | 23+ |
| gcloud CLI | Any recent (for Vertex AI auth) |

### 3.2 Install dependencies

```bash
pip install -r requirements.txt
```

Key packages:
- `google-adk` — Agent Development Kit
- `google-genai` — Gemini API client
- `mcp` — Model Context Protocol library
- `fastapi` + `uvicorn` — web server
- `pydantic` — schema validation
- `yfinance` — stock price data
- `python-dotenv` — environment variable loading

### 3.3 Authentication — Two options

**Option A: Vertex AI (recommended for production)**

```bash
gcloud auth application-default login
```

Then in `.env`:
```
GOOGLE_GENAI_USE_VERTEXAI=True
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

**Option B: Gemini API Key (simpler, rate-limited)**

Get a key at https://aistudio.google.com/apikey, then in `.env`:
```
GOOGLE_GENAI_USE_VERTEXAI=False
GEMINI_API_KEY=your_key_here
```

### 3.4 Copy and fill in the `.env` file

```bash
cp .env.example .env
# edit .env with your values
```

---

## 4. Running Without the Frontend (CLI)

Both the orchestrator and backtest runner expose `__main__` entry points.

### Live analysis

```bash
python -m agents.orchestrator.orchestrator --ticker JNJ --mode live
```

### Backtest analysis

```bash
python -m agents.orchestrator.orchestrator --ticker NVO --mode backtest --date 2023-06-01
```

Output is a JSON blob printed to stdout.

### Backtest runner (with scoring)

```bash
python -m backtest.runner --pairs JNJ:2023-01-15 PFE:2023-09-01 NVO:2023-03-20
```

Output includes the prediction, forward return (fetched *after* prediction is locked), direction correctness, and magnitude hit.

### Test a single MCP server directly

```bash
# Start the clinical trials MCP server in stdio mode, then query it manually
python mcp_servers/clinical_trials.py
```

---

## 5. Running the Web Frontend

```bash
python frontend/server.py
```

Then open **http://localhost:8000** in your browser.

Alternatively with hot-reload for development:
```bash
uvicorn frontend.server:app --reload --port 8000
```

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves `frontend/static/index.html` |
| GET | `/api/tickers` | Returns `["AMGN", "GSK", "JNJ", "NVO", "PFE"]` |
| POST | `/api/predict` | Full pipeline (live or backtest) |
| POST | `/api/backtest` | Single dated backtest with scoring |
| GET | `/health` | Simple `{"status": "ok"}` |

#### POST `/api/predict` — request body

```json
{
  "ticker": "JNJ",
  "mode": "live"
}
```

Backtest:
```json
{
  "ticker": "PFE",
  "mode": "backtest",
  "as_of_date": "2023-06-01"
}
```

#### Response shape

```json
{
  "ticker": "JNJ",
  "mode": "live",
  "as_of_date": "2025-07-01",
  "indicator_outputs": [
    {
      "indicator": "Clinical Trial Execution",
      "ticker": "JNJ",
      "as_of_date": "2025-07-01",
      "signal": "bullish",
      "confidence": 0.8,
      "magnitude": 0.03,
      "reasoning": "...",
      "key_evidence": ["..."],
      "sources": ["ClinicalTrials.gov"],
      "data_as_of_lag_days": 14
    }
  ],
  "price_context": { ... },
  "ensemble": {
    "overall_signal": "bullish",
    "confidence": 0.72,
    "magnitude": 0.025,
    "magnitude_range": "+1% to +3%",
    "reasoning": "..."
  },
  "report": "# JNJ Analysis\n\n...",
  "execution_time_seconds": 42.3
}
```

---

## 6. How Each Component Works

### 6.1 MCP Servers

Each MCP server in `mcp_servers/` is an independent Python process that communicates over `stdio` using the Model Context Protocol. It exposes exactly **one tool** that the corresponding agent calls.

| File | Tool name | Data source | Key parameter |
|------|-----------|-------------|---------------|
| `clinical_trials.py` | `get_clinical_trials` | ClinicalTrials.gov v2 REST | `as_of_date` |
| `cms_prescriber.py` | `get_prescriber_signals` | CMS Medicare Part D PUF | `as_of_date` |
| `pubmed.py` | `get_pubmed_momentum` | NCBI PubMed E-utilities | `as_of_date` |
| `usaspending.py` | `get_government_contracts` | USAspending.gov API | `as_of_date` |
| `gdelt.py` | `get_headline_sentiment` | GDELT GKG v2 | `as_of_date` |
| `price_data.py` | `get_price_data` / `get_forward_returns` | yfinance | `as_of_date` |

**Lookahead prevention:** Every MCP server accepts `as_of_date`. In backtest mode, it applies a data-lag constant before filtering to ensure only genuinely historical data is returned (see §7).

### 6.2 Indicator Agents

Each indicator agent in `agents/indicators/` follows the same pattern:

1. Instantiate a Gemini agent (`google.adk.agents.Agent`) with one tool — the corresponding MCP server's tool.
2. Call `agent.run(prompt)` via ADK's `InMemoryRunner`.
3. Parse the model's structured JSON output into an `IndicatorOutput` Pydantic object.
4. Return it.

All agents implement **graceful degradation**: if the MCP call fails (network error, API limit, 403), the agent catches the exception and returns a neutral `IndicatorOutput` with `confidence=0.3`. This prevents one failing agent from crashing the whole pipeline.

### 6.3 Price Data Agent

- **Live mode**: returns the last 90 days of OHLCV data from yfinance.
- **Backtest mode**: returns OHLCV up to (but not including) `as_of_date`.
- **Forward returns** (used by backtest runner only): fetched *after* the prediction is stored, via `get_forward_returns()`.

### 6.4 Ensemble Agent

Receives all five `IndicatorOutput` objects. Weighs them by:
- `confidence × magnitude` per indicator
- Predefined domain weights (clinical trials > prescriber adoption > publications > procurement > sentiment)

Returns an `EnsembleOutput` with `overall_signal`, `confidence`, `magnitude`, and `magnitude_range`.

### 6.5 Report Writer Agent

Receives the ensemble output + all indicator outputs + price context. Generates a human-readable markdown narrative explaining:
- The overall prediction and rationale
- How each indicator contributed
- Key risks and caveats
- Notable recent events (from evidence fields)

### 6.6 Orchestrator

`agents/orchestrator/orchestrator.py` coordinates everything:

```python
results = await asyncio.gather(
    run_clinical_trials(ticker, as_of_date),
    run_physician_adoption(ticker, as_of_date),
    run_pubmed(ticker, as_of_date),
    run_usaspending(ticker, as_of_date),
    run_gdelt(ticker, as_of_date),
    run_price_data(ticker, as_of_date),
    return_exceptions=True,   # ← never crashes on agent failure
)
```

All six agents run concurrently. Exceptions are converted to neutral fallbacks. Results are passed sequentially to the ensemble and report writer.

### 6.7 Backtest Runner

`backtest/runner.py` enforces the strict anti-lookahead protocol:

```
1. Call run_analysis(ticker, mode="backtest", as_of_date=date)
   → prediction stored
2. ONLY THEN call get_forward_returns(ticker, date, forward_days=5)
   → forward return fetched
3. Score: direction_correct, magnitude_hit
```

The forward return is **never** passed to any agent.

---

## 7. Data Sources & Lookahead Bias

| Source | Release lag | Applied in |
|--------|-------------|-----------|
| ClinicalTrials.gov | ~14 days | `clinical_trials.py` |
| CMS Prescriber PUF | 18–21 months | `cms_prescriber.py` |
| PubMed | ~7 days (indexing lag) | `pubmed.py` |
| USAspending.gov | 30–90 days | `usaspending.py` |
| GDELT | ~24 hours | `gdelt.py` |
| yfinance (price) | Real-time in live mode | `price_data.py` |

In backtest mode each MCP server internally computes `effective_date = as_of_date - lag` and only returns records with `update_date ≤ effective_date`.

---

## 8. Adding a New Indicator

1. **Create the MCP server** in `mcp_servers/my_new_source.py`.  
   Expose a single `@server.call_tool()` handler that accepts `ticker` and `as_of_date`.

2. **Create the agent** in `agents/indicators/my_new_agent.py`.  
   Follow the same pattern as `clinical_trials_agent.py`:
   - Build the MCP server process reference
   - Instantiate `google.adk.agents.Agent` with the tool
   - Parse output into `IndicatorOutput`

3. **Register in the orchestrator**:  
   - Import the new `run` function at the top of `orchestrator.py`
   - Add it to the `asyncio.gather()` call
   - Add its name to `indicator_names`

4. **Update the ensemble agent** weights in `ensemble_agent.py` if needed.

5. **Update `DEVELOPER_GUIDE.md`** and `README.md`.

---

## 9. Testing & Validation

### Unit testing a single agent

```bash
# Replace with any agent module
python -m agents.indicators.clinical_trials_agent --ticker JNJ
```

### Validating schema compliance

Each agent should return an `IndicatorOutput` with all required fields:

```python
from agents.schemas import IndicatorOutput
output = IndicatorOutput.model_validate(raw_dict)  # raises if invalid
```

Required fields: `indicator`, `ticker`, `as_of_date`, `signal`, `confidence`, `magnitude`.  
`signal` must be `"bullish"`, `"bearish"`, or `"neutral"`.  
`confidence` must be in `[0.0, 1.0]`.

### End-to-end smoke test

```bash
python -m agents.orchestrator.orchestrator --ticker JNJ --mode live
```

A successful run returns a JSON blob in ~30–90 seconds.

---

## 10. Deployment

### Local (development)

```bash
python frontend/server.py
# → http://localhost:8000
```

### Google Cloud Run

```bash
# Build and push container
gcloud builds submit --tag gcr.io/YOUR_PROJECT/medtech-analyst

# Deploy
gcloud run deploy medtech-analyst \
  --image gcr.io/YOUR_PROJECT/medtech-analyst \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1
```

A `Dockerfile` for this deployment:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
CMD ["python", "frontend/server.py"]
```

### Streamlit Community Cloud (alternative — no auth needed)

Not recommended for this stack (FastAPI + static frontend) — use Cloud Run instead.

---

## 11. Common Errors

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `UserWarning: authenticated using end user credentials without a quota project` | ADC set but no quota project | Run `gcloud auth application-default set-quota-project YOUR_PROJECT` |
| `403 Forbidden` from ClinicalTrials.gov | IP-rate-limited or permission issue | Agent falls back to neutral signal automatically |
| `ModuleNotFoundError: google.adk` | ADK not installed | `pip install google-adk` |
| `ValueError: Unsupported ticker 'XYZ'` | Ticker not in universe | Use JNJ, NVO, PFE, AMGN, or GSK |
| `as_of_date is required in backtest mode` | Missing date in request | Pass `as_of_date` field in POST body |
| `yfinance: No data found` | Weekend / holiday / future date | Use a business day in the past |
| ADK `InMemoryRunner` hangs | MCP server subprocess crashed | Check logs; MCP server likely threw an exception |
