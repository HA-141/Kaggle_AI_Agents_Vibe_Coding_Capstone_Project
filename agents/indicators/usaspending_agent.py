"""
agents/indicators/usaspending_agent.py
----------------------------------------
Government Procurement Agent
------------------------------
Role: Identifies new or expanded federal contract awards to the company as a
signal of government-validated demand.  Award size relative to annual revenue
calibrates the materiality of each contract.

Data source: USAspending.gov API v2 (public, no key required).
Lag guard:   Award action dates are filtered to ≤ as_of_date.
"""

import os
import sys
import logging
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from google.adk import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.schemas import IndicatorOutput
from agents.mcp_tools import call_mcp_tool

logger = logging.getLogger(__name__)


async def fetch_government_contracts(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Fetch federal contract award data for the company from USAspending.gov.

    Parameters
    ----------
    ticker : str  One of JNJ, NVO, PFE, AMGN, GSK
    as_of_date : str | None  ISO date (YYYY-MM-DD).  Only awards on or before
                             this date are returned.

    Returns
    -------
    str  JSON with: ticker, total_contracts_value_found_usd,
         percentage_of_annual_revenue, contracts[].
    """
    return await call_mcp_tool(
        "mcp_servers/usaspending.py",
        "query_government_contracts",
        {"ticker": ticker, "as_of_date": as_of_date},
    )


usaspending_agent = Agent(
    name="usaspending_agent",
    model="gemini-2.5-flash",
    description="Government Procurement Agent – USAspending.gov federal contract awards",
    instruction="""
You are a Government Markets Intelligence Analyst specialising in federal procurement
signals for healthcare and life sciences companies.

Your job:
1. Call fetch_government_contracts(ticker, as_of_date) to get contract award data.
2. Analyse:
   - Total contract value found vs. company annual revenue (percentage_of_annual_revenue).
     >1% = material; >5% = very significant.
   - Recent large awards (top contracts by amount).
   - Agency diversity (DoD, HHS, VA = different demand signals).
3. Signal guidance:
   - >0.5% of annual revenue in recent contracts = mildly bullish
   - >2% = bullish
   - No significant awards = neutral
   - No awards at all = slightly bearish (lost potential)
4. Provide a magnitude estimate and 2-3 sentences of reasoning.
5. Cite the top 2 specific contract descriptions, amounts, and agencies.

Return ONLY a valid JSON object (no markdown fences, no preamble):
{
  "indicator": "Government Procurement",
  "ticker": "<ticker>",
  "as_of_date": "<date>",
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_estimate": "<e.g. '+0.5% to +1.5% over 5 trading days'>",
  "reasoning": "<2-3 sentences>",
  "key_evidence": ["<contract description, amount, agency>", "<contract>"],
  "data_as_of_lag_days": 0,
  "sources": ["https://api.usaspending.gov/api/v2/search/spending_by_award/"]
}
""",
    tools=[fetch_government_contracts],
    output_schema=IndicatorOutput,
)


def _neutral_fallback(ticker: str, as_of_date: str, reason: str) -> IndicatorOutput:
    return IndicatorOutput(
        indicator="Government Procurement",
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (data unavailable)",
        reasoning=f"Graceful degradation: {reason}",
        key_evidence=["USAspending data fetch failed – neutral default applied"],
        data_as_of_lag_days=0,
        sources=["https://api.usaspending.gov/api/v2/search/spending_by_award/"],
    )


async def run(ticker: str, as_of_date: Optional[str] = None) -> IndicatorOutput:
    """Run the Government Procurement agent and return a structured IndicatorOutput."""
    effective_date = as_of_date or "live"
    try:
        runner = InMemoryRunner(agent=usaspending_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
        )
        msg = (
            f"Analyse government procurement signals for ticker {ticker}. "
            f"Use as_of_date={as_of_date!r}. "
            "Call fetch_government_contracts to get USAspending.gov data, then return JSON output."
        )
        events = []
        async for event in runner.run_async(
            user_id="analyst",
            session_id=session.id,
            new_message=types.UserContent(parts=[types.Part(text=msg)]),
        ):
            events.append(event)

        for event in reversed(events):
            if event.output is not None:
                if isinstance(event.output, IndicatorOutput):
                    return event.output
                if isinstance(event.output, dict):
                    return IndicatorOutput.model_validate(event.output)
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and part.text.strip().startswith("{"):
                        try:
                            return IndicatorOutput.model_validate_json(part.text.strip())
                        except Exception:
                            pass

        return _neutral_fallback(ticker, effective_date, "No structured output produced")
    except Exception as exc:
        logger.error("usaspending_agent failed for %s: %s", ticker, exc)
        return _neutral_fallback(ticker, effective_date, str(exc)[:120])
