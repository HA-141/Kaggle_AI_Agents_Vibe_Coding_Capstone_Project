"""
agents/indicators/pubmed_agent.py
----------------------------------
Scientific Publication Momentum Agent
---------------------------------------
Role: Tracks whether academic and clinical research interest in the company's
key drugs is accelerating or decelerating, as a leading indicator of future
commercial momentum.

Data source: PubMed E-utilities API (public, no key required).
Lag guard:   A 14-day buffer is subtracted from as_of_date before querying so
             that papers indexed but not yet widely distributed are excluded.
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


async def fetch_pubmed_trends(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Fetch 6-month rolling publication counts for the company's key drugs from PubMed.

    Parameters
    ----------
    ticker : str  One of JNJ, NVO, PFE, AMGN, GSK
    as_of_date : str | None  ISO date (YYYY-MM-DD).  A 14-day buffer is applied.

    Returns
    -------
    str  JSON with: ticker, search_term, history (6 windows of 30 days each),
         recent_60d_publications, previous_60d_publications, trend_60d_change_pct.
    """
    return await call_mcp_tool(
        "mcp_servers/pubmed.py",
        "query_pubmed_trends",
        {"ticker": ticker, "as_of_date": as_of_date},
    )


pubmed_agent = Agent(
    name="pubmed_agent",
    model="gemini-2.5-flash",
    description="Scientific Publication Momentum Agent – PubMed publication trends",
    instruction="""
You are a Scientific Intelligence Analyst specialising in bibliometrics and
clinical literature trends.

Your job:
1. Call fetch_pubmed_trends(ticker, as_of_date) to get 6 monthly windows of
   publication counts for the company's key drugs.
2. Calculate the month-over-month (MoM) trend: is the count accelerating,
   stable, or decelerating?
   - recent_60d_publications > previous_60d_publications by ≥10% = accelerating = bullish
   - recent < previous by ≥10% = decelerating = bearish
   - Otherwise = neutral
3. Note any acceleration (positive change in MoM delta) or deceleration.
4. Synthesise into ONE signal and provide a magnitude estimate.
5. Write 2-3 sentences of reasoning with specific numbers.

Return ONLY a valid JSON object (no markdown fences, no preamble):
{
  "indicator": "Scientific Publication Momentum",
  "ticker": "<ticker>",
  "as_of_date": "<date>",
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_estimate": "<e.g. '+1% to +2% over 5 trading days'>",
  "reasoning": "<2-3 sentences>",
  "key_evidence": ["<stat with source>", "<stat>"],
  "data_as_of_lag_days": 14,
  "sources": ["https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"]
}
""",
    tools=[fetch_pubmed_trends],
    output_schema=IndicatorOutput,
)


def _neutral_fallback(ticker: str, as_of_date: str, reason: str) -> IndicatorOutput:
    return IndicatorOutput(
        indicator="Scientific Publication Momentum",
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (data unavailable)",
        reasoning=f"Graceful degradation: {reason}",
        key_evidence=["PubMed data fetch failed – neutral default applied"],
        data_as_of_lag_days=14,
        sources=["https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"],
    )


async def run(ticker: str, as_of_date: Optional[str] = None) -> IndicatorOutput:
    """Run the PubMed Momentum agent and return a structured IndicatorOutput."""
    effective_date = as_of_date or "live"
    try:
        runner = InMemoryRunner(agent=pubmed_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
        )
        msg = (
            f"Analyse scientific publication momentum for ticker {ticker}. "
            f"Use as_of_date={as_of_date!r}. "
            "Call fetch_pubmed_trends to get data, then return JSON output."
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
        logger.error("pubmed_agent failed for %s: %s", ticker, exc)
        return _neutral_fallback(ticker, effective_date, str(exc)[:120])
