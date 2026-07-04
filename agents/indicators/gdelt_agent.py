"""
agents/indicators/gdelt_agent.py
----------------------------------
Headline Sentiment Agent
--------------------------
Role: Measures the volume and tone of news coverage about the company.
This is the "mainstream baseline" signal — the Ensemble Agent uses its output
to classify the other four indicators as either:
  • "mainstream" (already reflected in headlines → likely priced in)
  • "under-covered" (not yet in headlines → potential alpha source)

Data source: GDELT Doc API v2 (public, full historical coverage with timestamps).
Lag guard:   Article date is filtered to ≤ as_of_date.
Fallback:    Deterministic mock data if GDELT returns HTTP 429 (rate limit).
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


async def fetch_headline_sentiment(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Fetch recent news headlines and aggregate sentiment scores for the company.

    Parameters
    ----------
    ticker : str  One of JNJ, NVO, PFE, AMGN, GSK
    as_of_date : str | None  ISO date (YYYY-MM-DD).  Headlines after this date
                             are excluded.

    Returns
    -------
    str  JSON with: ticker, total_articles, average_sentiment_tone,
         headline_sentiment, articles[{title, tone, seendate, domain}].
    """
    return await call_mcp_tool(
        "mcp_servers/gdelt.py",
        "query_headlines_sentiment",
        {"ticker": ticker, "as_of_date": as_of_date},
    )


gdelt_agent = Agent(
    name="gdelt_agent",
    model="gemini-2.5-flash",
    description="Headline Sentiment Agent – GDELT media coverage baseline (mainstream signal)",
    instruction="""
You are a Media Intelligence Analyst specialising in financial news sentiment analysis.

Your role is special: your output serves as the MAINSTREAM BASELINE for the Ensemble Agent.
The other four indicators will be compared against your signal to determine whether they
are already priced into public news or are under-covered leading signals.

Your job:
1. Call fetch_headline_sentiment(ticker, as_of_date) to get GDELT headline data.
2. Analyse:
   - average_sentiment_tone: >1.5 = clearly positive; <-1.5 = clearly negative
   - total_articles: high volume = high mainstream awareness
   - Scan headline titles for recurring themes (regulatory, earnings, litigation, pipeline)
3. Signal guidance:
   - avg_tone > 1.5 AND high volume = bullish (mainstream optimism)
   - avg_tone < -1.5 AND high volume = bearish (mainstream pessimism)
   - Mixed or low volume = neutral
4. Note: this is the MAINSTREAM signal. High confidence here means the news
   is widely known and likely already priced into the stock.
5. Provide a magnitude estimate and 2-3 sentences of reasoning.

Return ONLY a valid JSON object (no markdown fences, no preamble):
{
  "indicator": "Headline Sentiment",
  "ticker": "<ticker>",
  "as_of_date": "<date>",
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_estimate": "<e.g. '+1% to +2% over 5 trading days'>",
  "reasoning": "<2-3 sentences>",
  "key_evidence": ["<headline title or stat with source>", "<headline or stat>"],
  "data_as_of_lag_days": 0,
  "sources": ["https://api.gdeltproject.org/api/v2/doc/doc"]
}
""",
    tools=[fetch_headline_sentiment],
    output_schema=IndicatorOutput,
)


def _neutral_fallback(ticker: str, as_of_date: str, reason: str) -> IndicatorOutput:
    return IndicatorOutput(
        indicator="Headline Sentiment",
        ticker=ticker,
        as_of_date=as_of_date or "live",
        signal="neutral",
        confidence=0.3,
        magnitude_estimate="0% (data unavailable)",
        reasoning=f"Graceful degradation: {reason}",
        key_evidence=["GDELT data fetch failed – neutral default applied"],
        data_as_of_lag_days=0,
        sources=["https://api.gdeltproject.org/api/v2/doc/doc"],
    )


async def run(ticker: str, as_of_date: Optional[str] = None) -> IndicatorOutput:
    """Run the Headline Sentiment agent and return a structured IndicatorOutput."""
    effective_date = as_of_date or "live"
    try:
        runner = InMemoryRunner(agent=gdelt_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
        )
        msg = (
            f"Analyse headline sentiment for ticker {ticker}. "
            f"Use as_of_date={as_of_date!r}. "
            "Call fetch_headline_sentiment to get GDELT data, then return JSON output."
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
        logger.error("gdelt_agent failed for %s: %s", ticker, exc)
        return _neutral_fallback(ticker, effective_date, str(exc)[:120])
