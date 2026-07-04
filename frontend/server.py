"""
frontend/server.py
-------------------
FastAPI backend that:
  • Serves frontend/static/index.html on GET /
  • POST /api/predict   → runs the orchestrator in live or backtest mode
  • POST /api/backtest  → runs a single dated backtest and returns prediction + score

Start with:
    python frontend/server.py
or:
    uvicorn frontend.server:app --reload --port 8000
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional

# ── Ensure project root is on sys.path ──────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

from agents.orchestrator.orchestrator import run_analysis, SUPPORTED_TICKERS
from backtest.runner import run_backtest_pair

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware
import re
from datetime import datetime

app = FastAPI(
    title="MedTech Stock Analyst API",
    description="Multi-agent stock prediction for JNJ, NVO, PFE, AMGN, GSK",
    version="1.0.0",
)

# Enable CORS for security and cross-origin access control
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Can be configured to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ─────────────────────────────────────────────────────────────
STATIC_DIR = _HERE / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the main UI."""
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Request schemas ──────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    ticker: str
    mode: str = "live"          # "live" | "backtest"
    as_of_date: Optional[str] = None   # required when mode == "backtest"

class BacktestRequest(BaseModel):
    ticker: str
    as_of_date: str             # YYYY-MM-DD
    forward_days: int = 5


# ── Validation Helpers ───────────────────────────────────────────────────────

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def validate_ticker(ticker: str) -> str:
    ticker_clean = ticker.upper().strip()
    if ticker_clean not in SUPPORTED_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported ticker '{ticker}'. Supported: {sorted(SUPPORTED_TICKERS)}"
        )
    return ticker_clean

def validate_as_of_date(as_of_date: Optional[str], required: bool = False) -> Optional[str]:
    if not as_of_date:
        if required:
            raise HTTPException(
                status_code=400,
                detail="as_of_date is required for this operation."
            )
        return None
        
    if not DATE_PATTERN.match(as_of_date):
        raise HTTPException(
            status_code=400,
            detail="as_of_date must be in YYYY-MM-DD format."
        )
    try:
        datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="as_of_date is not a valid calendar date."
        )
    return as_of_date


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/tickers")
async def get_tickers():
    """Return the list of supported tickers."""
    return {"tickers": sorted(SUPPORTED_TICKERS)}


@app.post("/api/predict")
async def predict(req: PredictRequest):
    """
    Run the full multi-agent analysis pipeline.

    In live mode: fetches the latest available data for each indicator.
    In backtest mode: filters every data source to only information that was
    genuinely public on or before `as_of_date`.

    Returns the full orchestrator payload.
    """
    ticker = validate_ticker(req.ticker)
    
    if req.mode not in ("live", "backtest"):
        raise HTTPException(
            status_code=400,
            detail="mode must be 'live' or 'backtest'."
        )
        
    as_of_date = validate_as_of_date(req.as_of_date, required=(req.mode == "backtest"))

    logger.info("predict request: ticker=%s mode=%s as_of_date=%s", ticker, req.mode, as_of_date)

    try:
        result = await run_analysis(
            ticker=ticker,
            mode=req.mode,
            as_of_date=as_of_date,
        )
        return JSONResponse(content=result)
    except Exception as exc:
        logger.error("predict failed for %s: %s", ticker, exc, exc_info=True)
        # Avoid leaking internal system information by using a clean user-facing message
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while processing the prediction."
        )


@app.post("/api/backtest")
async def backtest_single(req: BacktestRequest):
    """
    Run a single dated backtest: predict, then score against actual forward return.
    """
    ticker = validate_ticker(req.ticker)
    as_of_date = validate_as_of_date(req.as_of_date, required=True)
    
    if not (1 <= req.forward_days <= 30):
        raise HTTPException(
            status_code=400,
            detail="forward_days must be between 1 and 30."
        )

    logger.info("backtest request: ticker=%s date=%s fwd_days=%d", ticker, as_of_date, req.forward_days)

    try:
        result = await run_backtest_pair(
            ticker=ticker,
            as_of_date=as_of_date,
            forward_days=req.forward_days,
        )
        return JSONResponse(content=result)
    except Exception as exc:
        logger.error("backtest failed for %s: %s", ticker, exc, exc_info=True)
        # Clean response message
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while processing the backtest."
        )


@app.get("/health")
async def health():
    """Simple health check."""
    return {"status": "ok"}


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n{'='*60}")
    print(f"  MedTech Stock Analyst UI")
    print(f"  Open http://localhost:{port} in your browser")
    print(f"{'='*60}\n")
    uvicorn.run("frontend.server:app", host="0.0.0.0", port=port, reload=False)
