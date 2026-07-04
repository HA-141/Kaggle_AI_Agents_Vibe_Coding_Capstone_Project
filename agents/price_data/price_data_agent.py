"""
agents/price_data/price_data_agent.py
--------------------------------------
Price Data Agent
-----------------
Role: Fetches historical stock price context for the ticker.
  • In live mode:  returns recent 30-day price history as context.
  • In backtest mode: STRICTLY caps all price data at as_of_date.
    The forward return (needed for scoring) is NEVER returned here —
    it is obtained separately by the backtest runner AFTER the prediction
    is locked in. This is a hard architectural boundary.

Data source: yfinance (Yahoo Finance).
"""

import os
import sys
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from agents.mcp_tools import call_mcp_tool

logger = logging.getLogger(__name__)


async def run(ticker: str, as_of_date: Optional[str] = None) -> dict:
    """
    Fetch historical price context.  If as_of_date is set, no data after
    that date is returned (lookahead-bias prevention).

    Returns a dict with: ticker, prices[], latest_close, 30d_return_pct.
    On error returns a minimal dict with error key.
    """
    try:
        end = as_of_date or datetime.now().strftime("%Y-%m-%d")
        start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=45)
        start = start_dt.strftime("%Y-%m-%d")

        raw = await call_mcp_tool(
            "mcp_servers/price_data.py",
            "get_historical_prices",
            {"ticker": ticker, "start_date": start, "end_date": end, "as_of_date": as_of_date},
        )
        data = json.loads(raw)
        prices = data.get("prices", [])
        if len(prices) >= 2:
            latest_close = prices[-1]["close"]
            oldest_close = prices[0]["close"]
            return_pct = round(((latest_close - oldest_close) / oldest_close) * 100, 2)
            data["latest_close"] = latest_close
            data["30d_return_pct"] = return_pct
        return data
    except Exception as exc:
        logger.error("price_data_agent failed for %s: %s", ticker, exc)
        return {"ticker": ticker, "error": str(exc), "prices": []}


async def get_forward_returns(ticker: str, as_of_date: str, forward_days: int = 5) -> dict:
    """
    BACKTEST SCORING ONLY – called by backtest/runner.py after prediction is logged.
    NEVER call this from orchestrator, ensemble, or indicator agents.
    """
    try:
        raw = await call_mcp_tool(
            "mcp_servers/price_data.py",
            "get_forward_returns",
            {"ticker": ticker, "as_of_date": as_of_date, "forward_days": forward_days},
        )
        return json.loads(raw)
    except Exception as exc:
        logger.error("get_forward_returns failed for %s: %s", ticker, exc)
        return {"ticker": ticker, "as_of_date": as_of_date, "error": str(exc)}
