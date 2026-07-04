"""
agents/indicators/clinical_trials_agent.py
------------------------------------------
Clinical Trial Execution Agent
--------------------------------
Role: Analyzes the *quality* of clinical trial execution for the given company,
not merely whether trials exist.  Signals are based on:
  • Enrollment speed vs. target (over-enrolling = bullish, stalling = bearish)
  • Status transitions (Recruiting→Active = positive; Terminated/Suspended = negative)
  • Timeline slippage vs. estimated completion dates
  • Frequency of protocol amendments (many = possible trouble)

Data source: ClinicalTrials.gov API v2 (public, no key required).
Lag guard: filter.advanced restricts results to LastUpdatePostDate ≤ as_of_date
           (~0 real-world lag for this dataset).
"""

import os
import sys
import json
import logging
from typing import Optional

# Ensure project root is on path for flat imports
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

# ---------------------------------------------------------------------------
# Tool function – called by the ADK agent at inference time
# ---------------------------------------------------------------------------

async def fetch_clinical_trials(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Fetch clinical trial data for the given company ticker from ClinicalTrials.gov.

    Parameters
    ----------
    ticker : str  One of JNJ, NVO, PFE, AMGN, GSK
    as_of_date : str | None  ISO date (YYYY-MM-DD).  If provided, only trials
                             updated on or before this date are returned.

    Returns
    -------
    str  JSON-encoded dict with keys: ticker, as_of_date, total_trials_found, trials[].
    """
    return await call_mcp_tool(
        "mcp_servers/clinical_trials.py",
        "query_clinical_trials",
        {"ticker": ticker, "as_of_date": as_of_date},
    )


# ---------------------------------------------------------------------------
# ADK Agent definition
# ---------------------------------------------------------------------------

clinical_trials_agent = Agent(
    name="clinical_trials_agent",
    model="gemini-2.5-flash",
    description="Clinical Trial Execution Agent – judges trial quality, not just existence",
    instruction="""
You are an expert Clinical Trial Analyst specialising in pharma / medtech trial execution.

Your job:
1. Call fetch_clinical_trials(ticker, as_of_date) to obtain trial data.
2. Analyse execution QUALITY across the returned trials:
   - Enrollment: Is enrollment_count reaching enrollment_type="ACTUAL" or lagging?
   - Status signals: Count trials by status. Active/Completed = positive; Terminated/
     Suspended/Withdrawn = negative.
   - Timeline slippage: Compare start_date + expected duration vs. completion_date.
     If completion_type="ESTIMATED" and last_update_posted is past that date, it has slipped.
   - Volume trend: More active trials than prior period = positive pipeline momentum.
3. Synthesise these signals into ONE overall signal (bullish / bearish / neutral).
4. Provide a magnitude_estimate such as "+1% to +3% over 5 trading days".
5. Write 2-3 sentences of plain-language reasoning and list 2–3 concrete evidence facts.

Return ONLY a valid JSON object matching this schema (no markdown, no extra text):
{
  "indicator": "Clinical Trial Execution",
  "ticker": "<ticker>",
  "as_of_date": "<date>",
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_estimate": "<e.g. '+2% to +4% over 5 trading days'>",
  "reasoning": "<2-3 sentences>",
  "key_evidence": ["<fact with source NCT/URL>", "<fact>"],
  "data_as_of_lag_days": 0,
  "sources": ["https://clinicaltrials.gov/api/v2/studies"]
}
""",
    tools=[fetch_clinical_trials],
    output_schema=IndicatorOutput,
)


# ---------------------------------------------------------------------------
# Standalone runner – called by the orchestrator
# ---------------------------------------------------------------------------

def _neutral_fallback(ticker: str, as_of_date: str, reason: str) -> IndicatorOutput:
    return IndicatorOutput(
        indicator="Clinical Trial Execution",
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (data unavailable)",
        reasoning=f"Graceful degradation: {reason}",
        key_evidence=["Agent execution failed – neutral default applied"],
        data_as_of_lag_days=0,
        sources=["https://clinicaltrials.gov/api/v2/studies"],
    )


async def run(ticker: str, as_of_date: Optional[str] = None) -> IndicatorOutput:
    """
    Execute the Clinical Trials agent and return a structured IndicatorOutput.
    Errors are caught and converted to a neutral fallback so one failure cannot
    crash the entire orchestration run.
    """
    effective_date = as_of_date or "live"
    try:
        runner = InMemoryRunner(agent=clinical_trials_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
        )
        msg = (
            f"Analyse clinical trial execution quality for ticker {ticker}. "
            f"Use as_of_date={as_of_date!r}. "
            "Call fetch_clinical_trials to get data, then return the JSON output."
        )
        events = []
        async for event in runner.run_async(
            user_id="analyst",
            session_id=session.id,
            new_message=types.UserContent(parts=[types.Part(text=msg)]),
        ):
            events.append(event)

        # Extract structured output
        for event in reversed(events):
            if event.output is not None:
                if isinstance(event.output, IndicatorOutput):
                    return event.output
                if isinstance(event.output, dict):
                    return IndicatorOutput.model_validate(event.output)
            # Try parsing text as JSON fallback
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        txt = part.text.strip()
                        if txt.startswith("{"):
                            try:
                                return IndicatorOutput.model_validate_json(txt)
                            except Exception:
                                pass

        return _neutral_fallback(ticker, effective_date, "No structured output produced")
    except Exception as exc:
        logger.error("clinical_trials_agent failed for %s: %s", ticker, exc)
        return _neutral_fallback(ticker, effective_date, str(exc)[:120])
