from pydantic import BaseModel, Field
from typing import List, Literal, Dict

class IndicatorOutput(BaseModel):
    indicator: str = Field(..., description="The name of the indicator analyzed")
    ticker: str = Field(..., description="The ticker of the analyzed company (e.g. JNJ)")
    as_of_date: str = Field(..., description="The reference date of the analysis (YYYY-MM-DD)")
    signal: Literal["bullish", "bearish", "neutral"] = Field(..., description="The signal recommendation: bullish, bearish, or neutral")
    confidence: float = Field(..., description="Confidence score from 0.0 (no confidence) to 1.0 (extreme certainty)", ge=0.0, le=1.0)
    magnitude_estimate: str = Field(..., description="Plain-language estimate of price impact (e.g., '+2% to +5% over 5 trading days')")
    reasoning: str = Field(..., description="A 2-3 sentence plain-language explanation of why this signal was given")
    key_evidence: List[str] = Field(..., description="Specific facts and observations, each citing its source")
    data_as_of_lag_days: int = Field(..., description="The real-world release lag of the data source in days relative to as_of_date")
    sources: List[str] = Field(..., description="The sources/endpoints used (URLs or dataset names)")

class EnsembleOutput(BaseModel):
    direction: Literal["bullish", "bearish", "neutral"] = Field(..., description="The overall synthesized price direction")
    confidence: float = Field(..., description="Overall confidence score from 0.0 to 1.0", ge=0.0, le=1.0)
    magnitude_range: str = Field(..., description="Synthesized plain-language range (e.g. '+1% to +3% over 5 trading days')")
    ranked_indicators: List[str] = Field(..., description="List of the 5 indicators ranked by estimated contribution (most important first)")
    indicator_tags: Dict[str, Literal["mainstream", "under-covered"]] = Field(..., description="Mapping of each of the 5 indicators to either 'mainstream' (priced in) or 'under-covered' (leading indicator) relative to Headline Sentiment")
    uncertainty_statement: str = Field(..., description="A clear, explicit statement of uncertainty explaining the limitations and risks of the call")
    synthesized_reasoning: str = Field(..., description="A unified narrative synthesis explaining the ranked drivers and thesis")
