"""
agents/ensemble_ranking/ensemble_agent.py
-------------------------------------------
Ensemble / Ranking Agent
--------------------------
Role: Synthesises the five indicator signals into a single weighted prediction.

Algorithm (done by the LLM given the structured inputs):
  1. Weighted-average direction: each indicator votes bullish/bearish/neutral
     weighted by its confidence score.  NOT a simple majority vote.
  2. Synthesised magnitude: derives a combined range from individual estimates,
     weighted by confidence.
  3. Ranking: orders indicators by estimated contribution to the call.
  4. Mainstream vs. under-covered tagging: compares each indicator's signal to
     the Headline Sentiment (GDELT) baseline signal.  If they agree, the signal
     is already in the news (mainstream / likely priced-in).  If they diverge,
     it may be an under-covered leading signal.
  5. Uncertainty statement: explicit, never claims certainty.

The Ensemble Agent is a pure reasoning agent — it does NOT call any external
data sources.  All data comes from the five IndicatorOutput objects passed in
as a structured message.
"""

import os
import sys
import json
import logging
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from google.adk import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.schemas import IndicatorOutput, EnsembleOutput

logger = logging.getLogger(__name__)


ensemble_agent = Agent(
    name="ensemble_agent",
    model="gemini-2.5-flash",
    description="Ensemble / Ranking Agent – synthesises five indicator signals into a weighted prediction",
    instruction="""
You are a Senior Quantitative Analyst synthesising multiple alternative data signals
into a single, rigorous stock prediction.

You will receive five indicator outputs in JSON format.  Your job:

1. WEIGHTED DIRECTION:
   Assign +1 (bullish), 0 (neutral), -1 (bearish) to each signal.
   Multiply each by its confidence score.  Sum the weighted values.
   If sum > 0.3 → overall = bullish
   If sum < -0.3 → overall = bearish
   Otherwise → neutral
   Also compute an overall confidence as the average of individual confidences.

2. SYNTHESISED MAGNITUDE:
   Take the magnitude_estimate strings from bullish indicators and find the
   intersection / overlap range.  Express as a single range (e.g. "+1% to +3%").

3. RANKED INDICATORS:
   Rank all 5 indicators from most to least impactful on the call.
   Consider: signal strength × confidence × data recency (inverse of lag_days).

4. MAINSTREAM vs. UNDER-COVERED:
   Use the "Headline Sentiment" indicator as the baseline.
   - If another indicator's signal AGREES with Headline Sentiment → "mainstream"
     (the information is likely already in public news and may be priced in).
   - If another indicator DIVERGES from Headline Sentiment → "under-covered"
     (potential alpha – not yet reflected in mainstream media).
   Tag each of the five indicators as "mainstream" or "under-covered".

5. UNCERTAINTY STATEMENT:
   Always include an explicit statement that this is probabilistic analysis of
   public data, not investment advice.  Never claim certainty.

Return ONLY a valid JSON object (no markdown fences, no preamble):
{
  "direction": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "magnitude_range": "<e.g. '+1% to +3% over 5 trading days'>",
  "ranked_indicators": ["<most impactful indicator name>", ..., "<least impactful>"],
  "indicator_tags": {
    "Clinical Trial Execution": "mainstream" | "under-covered",
    "Physician Adoption Signals": "mainstream" | "under-covered",
    "Scientific Publication Momentum": "mainstream" | "under-covered",
    "Government Procurement": "mainstream" | "under-covered",
    "Headline Sentiment": "mainstream"
  },
  "uncertainty_statement": "<explicit statement about uncertainty and limitations>",
  "synthesized_reasoning": "<3-5 sentence narrative explaining the call>"
}
""",
    tools=[],
    output_schema=EnsembleOutput,
)


def _neutral_ensemble(ticker: str, reason: str) -> EnsembleOutput:
    return EnsembleOutput(
        direction="neutral",
        confidence=0.3,
        magnitude_range="0% (fallback)",
        ranked_indicators=[
            "Headline Sentiment",
            "Clinical Trial Execution",
            "Physician Adoption Signals",
            "Scientific Publication Momentum",
            "Government Procurement",
        ],
        indicator_tags={
            "Clinical Trial Execution": "mainstream",
            "Physician Adoption Signals": "mainstream",
            "Scientific Publication Momentum": "mainstream",
            "Government Procurement": "mainstream",
            "Headline Sentiment": "mainstream",
        },
        uncertainty_statement=f"Ensemble failed ({reason}). This is a neutral fallback, not a real prediction.",
        synthesized_reasoning="Graceful degradation: ensemble agent could not process indicator outputs.",
    )


async def run(
    ticker: str,
    as_of_date: Optional[str],
    indicators: List[IndicatorOutput],
) -> EnsembleOutput:
    """
    Synthesise indicator outputs into a single ensemble prediction.

    Parameters
    ----------
    ticker : str
    as_of_date : str | None
    indicators : list[IndicatorOutput]  The five indicator signals.

    Returns
    -------
    EnsembleOutput  (or neutral fallback on error)
    """
    try:
        # Serialise the indicator outputs into a compact prompt
        indicators_json = json.dumps(
            [ind.model_dump() for ind in indicators],
            indent=2,
        )
        msg = (
            f"You have received the following five indicator signals for {ticker} "
            f"as of {as_of_date or 'today'}.\n\n"
            f"INDICATOR OUTPUTS:\n{indicators_json}\n\n"
            "Now synthesise these into a single ensemble prediction following your instructions."
        )

        runner = InMemoryRunner(agent=ensemble_agent, app_name="medtech_analyst")
        session = await runner.session_service.create_session(
            app_name="medtech_analyst", user_id="analyst"
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
                if isinstance(event.output, EnsembleOutput):
                    return event.output
                if isinstance(event.output, dict):
                    return EnsembleOutput.model_validate(event.output)
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and part.text.strip().startswith("{"):
                        try:
                            return EnsembleOutput.model_validate_json(part.text.strip())
                        except Exception:
                            pass

        return _neutral_ensemble(ticker, "No structured output produced")
    except Exception as exc:
        logger.error("ensemble_agent failed for %s: %s", ticker, exc)
        return _neutral_ensemble(ticker, str(exc)[:120])
