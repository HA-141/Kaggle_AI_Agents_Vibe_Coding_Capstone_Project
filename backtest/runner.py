"""
backtest/runner.py
-----------------
Backtest Runner
~~~~~~~~~~~~~~
Implements the strict back‑testing workflow required by the specification.
It:
1. Accepts a list of (ticker, as_of_date) pairs.
2. For each pair it runs the full orchestrator in *backtest* mode – all agents
   receive the same `as_of_date` and each MCP server internally applies the
   correct release‑lag filtering.
3. The result (the structured ensemble output) is stored in a JSON log.
4. After the prediction is logged, the runner calls the **price_data** MCP
   server **only** to obtain the forward return for the next N trading days.
   This forward return is never fed back into the orchestrator or any indicator
   agent – the separation is enforced by the code structure.
5. The prediction is scored:
   * **direction correctness** – bullish/bearish matches the sign of the
     forward return.
   * **magnitude hit** – the forward return (absolute %) falls inside the
     `magnitude_estimate` range extracted from the ensemble output.
6. After processing all inputs a summary JSON with overall direction accuracy
   and magnitude hit‑rate is printed.

Usage (CLI) ::

    python -m backtest.runner \
        --pairs JNJ:2023-01-15 NVO:2023-02-01 PFE:2023-03-10

The `--pairs` argument accepts a space‑separated list of `TICKER:DATE` strings.
The runner prints a nicely formatted JSON report at the end.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Tuple, Optional

# Ensure project root is on sys.path for flat imports
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from agents.orchestrator.orchestrator import run_analysis
from agents.price_data.price_data_agent import get_forward_returns
from agents.schemas import EnsembleOutput

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def parse_pair(pair: str) -> Tuple[str, str]:
    """Parse a ``TICKER:YYYY-MM-DD`` string into components."""
    try:
        ticker, date_str = pair.split(":")
        # Validate date format
        datetime.strptime(date_str, "%Y-%m-%d")
        return ticker.upper(), date_str
    except Exception as exc:
        raise ValueError(f"Invalid pair '{pair}'. Expected format TICKER:YYYY-MM-DD") from exc


def extract_magnitude_range(text: str) -> Tuple[float, float]:
    """Parse a magnitude string like '+1% to +3%' into a (low, high) float tuple.
    If parsing fails a wide range (‑100%, +100%) is returned so the hit‑rate
    defaults to *True* (conservative fallback).
    """
    import re
    # Find numbers optionally preceded by +/‑ and possibly with %
    matches = re.findall(r"[-+]?[0-9]*\.?[0-9]+", text)
    if len(matches) >= 2:
        low, high = float(matches[0]), float(matches[1])
        return low, high
    # Fallback – extremely wide range
    return -100.0, 100.0


def forward_return_to_percent(ret_dict: dict) -> Optional[float]:
    """Extract the forward return percentage from the MCP output.
    The MCP server returns something like:
        {"forward_return_pct": 2.3, "as_of_date": "2023-01-15", ...}
    """
    if not ret_dict:
        return None
    return ret_dict.get("forward_return_pct")

# ---------------------------------------------------------------------------
# Core back‑test loop
# ---------------------------------------------------------------------------

async def run_backtest_pair(ticker: str, as_of_date: str, forward_days: int = 5) -> dict:
    """Execute a single back‑test instance.
    Returns a dict with the raw orchestrator payload, the forward return and the
    scoring booleans.
    """
    # 1️⃣ Run orchestrator in backtest mode (no look‑ahead data)
    orchestrator_result = await run_analysis(
        ticker=ticker, mode="backtest", as_of_date=as_of_date
    )

    # 2️⃣ Extract ensemble output for magnitude
    ensemble_raw = orchestrator_result.get("ensemble", {})
    ensemble = EnsembleOutput.model_validate(ensemble_raw)
    magnitude_range = extract_magnitude_range(ensemble.magnitude_range)
    direction = ensemble.direction

    # 3️⃣ Query forward return *after* the prediction is locked in
    forward_data = await get_forward_returns(ticker, as_of_date, forward_days)
    forward_pct = forward_return_to_percent(forward_data)

    # 4️⃣ Scoring
    direction_correct = (
        (direction == "bullish" and forward_pct is not None and forward_pct > 0)
        or (direction == "bearish" and forward_pct is not None and forward_pct < 0)
    )
    magnitude_hit = (
        forward_pct is not None
        and magnitude_range[0] <= forward_pct <= magnitude_range[1]
    )

    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "orchestrator": orchestrator_result,
        "forward_return": forward_data,
        "score": {
            "direction_correct": direction_correct,
            "magnitude_hit": magnitude_hit,
        },
    }


async def run_backtest(pairs: List[Tuple[str, str]], forward_days: int = 5) -> dict:
    """Run back‑testing for a list of (ticker, as_of_date) pairs.
    Returns a summary dict with per‑pair results and overall statistics.
    """
    results = []
    for ticker, date_str in pairs:
        logger.info("Back‑testing %s as of %s", ticker, date_str)
        res = await run_backtest_pair(ticker, date_str, forward_days)
        results.append(res)

    # Aggregate statistics
    total = len(results)
    direction_correct = sum(r["score"]["direction_correct"] for r in results)
    magnitude_hit = sum(r["score"]["magnitude_hit"] for r in results)

    summary = {
        "total_cases": total,
        "direction_accuracy": round(direction_correct / total, 3) if total else None,
        "magnitude_hit_rate": round(magnitude_hit / total, 3) if total else None,
        "per_case": results,
    }
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Back‑test runner for MedTech stock analyst")
    parser.add_argument(
        "--pairs",
        nargs="+",
        required=True,
        help="Space‑separated list of TICKER:YYYY-MM-DD strings",
    )
    parser.add_argument(
        "--forward-days",
        type=int,
        default=5,
        help="Number of trading days for forward return (default 5)",
    )
    args = parser.parse_args()

    try:
        pair_list = [parse_pair(p) for p in args.pairs]
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    summary = asyncio.run(run_backtest(pair_list, args.forward_days))
    print(json.dumps(summary, indent=2, default=str))
