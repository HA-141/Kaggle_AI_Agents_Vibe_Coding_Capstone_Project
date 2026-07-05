# Architecture & Developer Guide

## Execution Flow

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

## Schema Definitions

### IndicatorOutput

| Field | Type | Description |
|---|---|---|
| `indicator` | `str` | Indicator name |
| `ticker` | `str` | Ticker (JNJ, NVO, PFE, AMGN, GSK) |
| `as_of_date` | `str` | Reference date (YYYY-MM-DD) |
| `signal` | `"bullish" \| "bearish" \| "neutral"` | Direction |
| `confidence` | `float [0,1]` | Confidence score |
| `magnitude_estimate` | `str` | Plain-language range (e.g. "+2% to +4%") |
| `reasoning` | `str` | 2-3 sentence explanation |
| `key_evidence` | `list[str]` | Specific facts with source citations |
| `data_as_of_lag_days` | `int` | Data source release lag in days |
| `sources` | `list[str]` | Source URLs or dataset names |

### EnsembleOutput

| Field | Type | Description |
|---|---|---|
| `direction` | `"bullish" \| "bearish" \| "neutral"` | Overall direction |
| `confidence` | `float [0,1]` | Synthesised confidence |
| `magnitude_range` | `str` | Combined magnitude range |
| `ranked_indicators` | `list[str]` | 5 indicators ranked by contribution |
| `indicator_tags` | `dict[str, "mainstream"\|"under-covered"]` | Coverage type per indicator |
| `uncertainty_statement` | `str` | Explicit risk statement |
| `synthesized_reasoning` | `str` | Unified narrative |

## Repository Structure

```
Kaggle-AI-Agents-MedTech-Stock-Analyst/
├── agents/
│   ├── __init__.py
│   ├── schemas.py              # Pydantic schemas
│   ├── mcp_tools.py            # MCP stdio client helper
│   ├── orchestrator/orchestrator.py
│   ├── indicators/             # 5 indicator agents
│   │   ├── clinical_trials_agent.py
│   │   ├── physician_adoption_agent.py
│   │   ├── pubmed_agent.py
│   │   ├── usaspending_agent.py
│   │   └── gdelt_agent.py
│   ├── price_data/price_data_agent.py
│   ├── ensemble_ranking/ensemble_agent.py
│   └── report_writer/report_writer_agent.py
├── mcp_servers/
│   ├── clinical_trials.py      # ClinicalTrials.gov API v2
│   ├── cms_prescriber.py       # CMS Medicare Part D PUF (hardcoded DB)
│   ├── pubmed.py               # NCBI PubMed E-utilities
│   ├── usaspending.py          # USAspending.gov API v2
│   ├── gdelt.py                # GDELT Doc API v2 (mock fallback)
│   └── price_data.py           # yfinance (OHLCV + forward returns)
├── backtest/runner.py          # Dated backtest + scoring
├── frontend/
│   ├── server.py               # FastAPI backend
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── tests/test_all.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── ARCHITECTURE.md
```

## MCP Server Details

| Server | Tool name(s) | Data source | Auth |
|---|---|---|---|
| `clinical_trials.py` | `query_clinical_trials` | ClinicalTrials.gov v2 REST | None |
| `cms_prescriber.py` | `query_prescriber_data` | CMS Medicare Part D PUF (curated DB) | None |
| `pubmed.py` | `query_pubmed_trends` | NCBI PubMed E-utilities | None |
| `usaspending.py` | `query_government_contracts` | USAspending.gov API v2 | None |
| `gdelt.py` | `query_headlines_sentiment` | GDELT Doc API v2 (mock fallback on 429) | None |
| `price_data.py` | `get_historical_prices`, `get_forward_returns` | yfinance | None |

All MCP servers are standalone Python processes using `FastMCP` and communicate over stdio. Logging goes to stderr. Each can be tested individually:

```bash
python mcp_servers/clinical_trials.py     # Ctrl+C to stop
```

## Indicator Agent Pattern

Each indicator agent follows the same pattern:

1. Define an `async` tool function that calls `call_mcp_tool()` pointing to the corresponding MCP server.
2. Create an `Agent` with `tools=[tool_fn]`, `output_schema=IndicatorOutput`, and a detailed instruction prompt.
3. Implement a `run()` function using `InMemoryRunner`.
4. On failure, return a neutral `IndicatorOutput` with `confidence=0.3` (graceful degradation).

## Lookahead Bias Prevention

| Source | Release lag | Applied in |
|---|---|---|
| ClinicalTrials.gov | ~14 days | `clinical_trials.py` — `filter.advanced` on `LastUpdatePostDate` |
| CMS Prescriber PUF | 18-21 months | `cms_prescriber.py` — year Y visible only after Oct 1 of Y+2 |
| PubMed | ~7 days (14-day buffer used) | `pubmed.py` — minus 14 days from as_of_date |
| USAspending.gov | 30-90 days | `usaspending.py` — time_period.end_date = as_of_date |
| GDELT | ~24 hours | `gdelt.py` — enddatetime = as_of_date |
| yfinance (price) | Real-time (live) / capped (backtest) | `price_data.py` — effective_end = min(end_date, as_of_date) |

In backtest mode, each MCP server receives `as_of_date` and applies its release lag internally. The price data agent returns **only** historical context — forward returns are fetched separately by the backtest runner **after** the prediction is stored.

## API Endpoints (FastAPI)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves frontend UI |
| GET | `/api/tickers` | `["AMGN", "GSK", "JNJ", "NVO", "PFE"]` |
| POST | `/api/predict` | Full pipeline (live or backtest) |
| POST | `/api/backtest` | Single dated backtest with scoring |
| GET | `/health` | `{"status": "ok"}` |

### POST /api/predict

```json
{"ticker": "JNJ", "mode": "live"}
{"ticker": "PFE", "mode": "backtest", "as_of_date": "2023-06-01"}
```

## Adding a New Indicator

1. Create the MCP server in `mcp_servers/my_source.py` with a tool accepting `ticker` and `as_of_date`.
2. Create the agent in `agents/indicators/my_agent.py` following the existing pattern.
3. Register in `agents/orchestrator/orchestrator.py` — add to imports, `asyncio.gather()`, and `indicator_names`.
4. Update ensemble weights in `agents/ensemble_ranking/ensemble_agent.py` if needed.
5. Update ARCHITECTURE.md.

## Deployment

### Local
```bash
python frontend/server.py
# → http://localhost:8000
```

### Google Cloud Run
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
CMD ["python", "frontend/server.py"]
```

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/medtech-analyst
gcloud run deploy medtech-analyst \
  --image gcr.io/YOUR_PROJECT/medtech-analyst \
  --platform managed --region us-central1 \
  --allow-unauthenticated \
   --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=True,\
    GOOGLE_GENAI_USE_ENTERPRISE=True,\
    GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,\
    GOOGLE_CLOUD_LOCATION=global
```

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `UserWarning: authenticated using end user credentials without a quota project` | ADC set but no quota project | `gcloud auth application-default set-quota-project YOUR_PROJECT` |
| `403 Forbidden` from ClinicalTrials.gov | IP rate-limit | Agent falls back to neutral automatically |
| `ModuleNotFoundError: google.adk` | ADK not installed | `pip install google-adk` |
| `ValueError: Unsupported ticker 'XYZ'` | Ticker not in universe | Use JNJ, NVO, PFE, AMGN, GSK |
| `as_of_date is required in backtest mode` | Missing date in request | Pass `as_of_date` field |
| `yfinance: No data found` | Weekend/holiday/future date | Use a past business day |
| `401 UNAUTHENTICATED` Vertex AI | Missing or expired credentials | Run `gcloud auth application-default login` |
| `429 prepayment credits depleted` (Developer API) | No billing on the Cloud project | Switch to Vertex AI, or add billing at https://console.cloud.google.com/billing |
