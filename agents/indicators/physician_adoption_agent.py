"""
agents/indicators/physician_adoption_agent.py
----------------------------------------------
Physician Adoption Signals Agent
----------------------------------
Role: Measures real-world physician uptake of the company's key drugs via
Medicare Part D prescriber data.  Signals are based on:
  • Year-over-year change in unique prescriber counts
  • Year-over-year change in total claim volume
  • Total drug cost trajectory (proxy for market penetration)

Data source: CMS Medicare Part D Prescriber Public Use File (local curated DB).
Lag guard:   Data year Y is only visible after October 1 of Y+2 (~21 months).
             The MCP server enforces this automatically based on as_of_date.
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


async def fetch_prescriber_data(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Fetch Medicare Part D prescriber adoption metrics for the company's key drugs.

    Parameters
    ----------
    ticker : str  One of JNJ, NVO, PFE, AMGN, GSK
    as_of_date : str | None  ISO date (YYYY-MM-DD).  Enforces the CMS 21-month
                             publication lag so only truly public data is visible.

    Returns
    -------
    str  JSON with keys: ticker, as_of_date, max_visible_data_year, data[].
         Each data row has: drug, year, prescribers, claims, cost,
         yoy_prescribers_growth_pct, yoy_claims_growth_pct, yoy_cost_growth_pct.
    """
    return await call_mcp_tool(
        "mcp_servers/cms_prescriber.py",
        "query_prescriber_data",
        {"ticker": ticker, "as_of_date": as_of_date},
    )


physician_adoption_agent = Agent(
    name="physician_adoption_agent",
    model="gemini-2.5-flash",
    description="Physician Adoption Signals Agent – CMS Medicare Part D prescriber trends",
    instruction="""
You are an expert Healthcare Markets Analyst specialising in drug commercialisation
and Medicare prescribing patterns.

Your job:
1. Call fetch_prescriber_data(ticker, as_of_date) to get Medicare Part D data.
2. Note the max_visible_data_year – this is the most recent year visible due to the
   18-24 month CMS publication lag. Do NOT speculate about years beyond this.
3. For each drug, identify the Year-over-Year (YoY) trends:
   - Prescribers: growing fast (>20% YoY) = strong adoption signal.
   - Claims: growing faster than prescribers = existing prescribers writing more scripts.
   - Declining metrics = loss of market momentum.
4. Synthesise all drugs into ONE signal (bullish / bearish / neutral).
5. Provide a magnitude_estimate and 2-3 sentences of reasoning.
6. List 2-3 concrete evidence items (drug name, year, YoY % from the data).

Return ONLY a valid JSON object (no markdown fences, no preamble):
{
  "indicator": "Physician Adoption Signals",
  "ticker": "<ticker>",
  "as_of_date": "<date>",
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_estimate": "<e.g. '+2% to +5% over 5 trading days'>",
  "reasoning": "<2-3 sentences>",
  "key_evidence": ["<drug, year, stat, source>", "<drug, year, stat>"],
  "data_as_of_lag_days": 630,
  "sources": ["CMS Medicare Part D Prescriber Public Use File"]
}
""",
    tools=[fetch_prescriber_data],
    output_schema=IndicatorOutput,
)


def _neutral_fallback(ticker: str, as_of_date: str, reason: str) -> IndicatorOutput:
    return IndicatorOutput(
        indicator="Physician Adoption Signals",
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (data unavailable)",
        reasoning=f"Graceful degradation: {reason}",
        key_evidence=["CMS data fetch failed – neutral default applied"],
        data_as_of_lag_days=630,
        sources=["CMS Medicare Part D Prescriber Public Use File"],
    )


async def run(ticker: str, as_of_date: Optional[str] = None) -> IndicatorOutput:
    """Run the Physician Adoption agent and return a structured IndicatorOutput."""
    effective_date = as_of_date or "live"
    try:
        runner = InMemoryRunner(agent=physician_adoption_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
        )
        msg = (
            f"Analyse physician adoption signals for ticker {ticker}. "
            f"Use as_of_date={as_of_date!r}. "
            "Call fetch_prescriber_data to get Medicare Part D data, then return JSON output."
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
        logger.error("physician_adoption_agent failed for %s: %s", ticker, exc)
        return _neutral_fallback(ticker, effective_date, str(exc)[:120])
