"""
agents/orchestrator/orchestrator.py
-------------------------------------
Main Orchestrator
------------------
Role: Accepts a ticker and mode (live / backtest), then coordinates
      all six sub-agents in parallel and assembles the final result.

Workflow:
  1. Validate inputs (ticker must be in SUPPORTED_TICKERS).
  2. Dispatch 6 agents concurrently via asyncio.gather():
       • 5 Indicator Agents (clinical_trials, physician_adoption, pubmed,
         usaspending, gdelt)
       • 1 Price Data Agent (historical context only, strictly date-capped)
  3. Convert any exceptions to neutral IndicatorOutput fallbacks.
  4. Pass the 5 indicator outputs to the Ensemble Agent.
  5. Pass ensemble + indicators + price context to the Report Writer.
  6. Return a rich result dict.

Lookahead bias prevention:
  In backtest mode, as_of_date is passed to every agent so each MCP server
  can filter data to only include information that was genuinely available on
  that date.  The Price Data Agent returns ONLY historical context — forward
  returns are NEVER included here.  The backtest runner calls get_forward_returns
  separately, AFTER this function has returned its prediction.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from agents.schemas import IndicatorOutput, EnsembleOutput
from agents.indicators.clinical_trials_agent import run as run_clinical_trials
from agents.indicators.physician_adoption_agent import run as run_physician_adoption
from agents.indicators.pubmed_agent import run as run_pubmed
from agents.indicators.usaspending_agent import run as run_usaspending
from agents.indicators.gdelt_agent import run as run_gdelt
from agents.price_data.price_data_agent import run as run_price_data
from agents.ensemble_ranking.ensemble_agent import run as run_ensemble
from agents.report_writer.report_writer_agent import run as run_report_writer

logger = logging.getLogger(__name__)

SUPPORTED_TICKERS = {"JNJ", "NVO", "PFE", "AMGN", "GSK"}


def _make_neutral_fallback(indicator_name: str, ticker: str, as_of_date: str, exc: Exception) -> IndicatorOutput:
    """Create a neutral IndicatorOutput when an agent fails."""
    return IndicatorOutput(
        indicator=indicator_name,
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (agent error)",
        reasoning=f"Agent failed with error: {str(exc)[:80]}. Neutral fallback applied.",
        key_evidence=["Agent execution failed – graceful degradation"],
        data_as_of_lag_days=0,
        sources=["System Fallback"],
    )


async def run_analysis(
    ticker: str,
    mode: str = "live",
    as_of_date: Optional[str] = None,
) -> dict:
    """
    Run the full multi-agent analysis pipeline.

    Parameters
    ----------
    ticker : str   One of JNJ, NVO, PFE, AMGN, GSK
    mode : str     "live" or "backtest"
    as_of_date : str | None
        Required in backtest mode (YYYY-MM-DD).
        In live mode, set to None to use today's data.

    Returns
    -------
    dict with keys:
        ticker, mode, as_of_date, indicator_outputs, price_context,
        ensemble, report, execution_time_seconds
    """
    ticker = ticker.upper().strip()
    if ticker not in SUPPORTED_TICKERS:
        raise ValueError(f"Unsupported ticker '{ticker}'. Must be one of: {sorted(SUPPORTED_TICKERS)}")

    effective_date = as_of_date if mode == "backtest" else None
    analysis_date = effective_date or datetime.now().strftime("%Y-%m-%d")

    logger.info("Starting analysis: ticker=%s mode=%s as_of_date=%s", ticker, mode, effective_date)
    start_time = datetime.now()

    # ── Step 1: Run all 6 agents in parallel ─────────────────────────────────
    raw_results = await asyncio.gather(
        run_clinical_trials(ticker, effective_date),
        run_physician_adoption(ticker, effective_date),
        run_pubmed(ticker, effective_date),
        run_usaspending(ticker, effective_date),
        run_gdelt(ticker, effective_date),
        run_price_data(ticker, effective_date),
        return_exceptions=True,
    )

    indicator_names = [
        "Clinical Trial Execution",
        "Physician Adoption Signals",
        "Scientific Publication Momentum",
        "Government Procurement",
        "Headline Sentiment",
    ]

    # ── Step 2: Separate and clean up results ─────────────────────────────────
    indicator_results = raw_results[:5]
    price_result = raw_results[5]

    clean_indicators: list[IndicatorOutput] = []
    for i, result in enumerate(indicator_results):
        if isinstance(result, Exception):
            logger.warning("Indicator agent '%s' failed: %s", indicator_names[i], result)
            clean_indicators.append(
                _make_neutral_fallback(indicator_names[i], ticker, analysis_date, result)
            )
        else:
            clean_indicators.append(result)

    price_context = (
        price_result
        if not isinstance(price_result, Exception)
        else {"ticker": ticker, "error": str(price_result), "prices": []}
    )

    # ── Step 3: Ensemble Agent ─────────────────────────────────────────────────
    logger.info("Running ensemble agent for %s", ticker)
    ensemble: EnsembleOutput = await run_ensemble(ticker, effective_date, clean_indicators)

    # ── Step 4: Report Writer ──────────────────────────────────────────────────
    logger.info("Running report writer for %s", ticker)
    report: str = await run_report_writer(
        ticker, effective_date, ensemble, clean_indicators, price_context
    )

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Analysis complete for %s in %.1fs", ticker, elapsed)

    return {
        "ticker": ticker,
        "mode": mode,
        "as_of_date": analysis_date,
        "indicator_outputs": [ind.model_dump() for ind in clean_indicators],
        "price_context": price_context,
        "ensemble": ensemble.model_dump(),
        "report": report,
        "execution_time_seconds": round(elapsed, 1),
    }


# ── CLI entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MedTech Stock Analyst – run live or backtest analysis")
    parser.add_argument("--ticker", required=True, help="Ticker symbol: JNJ, NVO, PFE, AMGN, GSK")
    parser.add_argument("--mode", default="live", choices=["live", "backtest"])
    parser.add_argument("--date", default=None, help="as_of_date (YYYY-MM-DD) for backtest mode")
    args = parser.parse_args()

    import json as _json
    result = asyncio.run(run_analysis(args.ticker, args.mode, args.date))
    print(_json.dumps(result, indent=2, default=str))
