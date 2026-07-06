import os
import sys
import logging
from typing import Any, Type, Optional
from dotenv import load_dotenv
from pydantic import BaseModel
from google.genai import types
from google.adk.runners import InMemoryRunner
from google.adk import Agent

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("agent_runner_helper")

async def run_adk_agent(
    agent: Agent, 
    user_message: str, 
    output_schema_class: Type[BaseModel]
) -> Any:
    """
    Runs an ADK agent with the given user message and returns the structured output.
    If the run fails, returns a fallback default instance of the output_schema_class.
    """
    logger.info(f"Running agent '{agent.name}' with message: {user_message}")
    
    # Check for API Key (not needed in Vertex/Enterprise mode)
    _is_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" or \
                 os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE", "").lower() == "true"
    if not _is_vertex and not os.environ.get("GEMINI_API_KEY"):
        logger.warning("Warning: GEMINI_API_KEY is not set in environment or .env file.")
        
    try:
        runner = InMemoryRunner(agent=agent)
        collected_events = []
        
        # Run agent asynchronously
        async for event in runner.run_async(
            user_id="analyst_user",
            session_id=f"session_{agent.name}",
            new_message=types.UserContent(parts=[types.Part(text=user_message)])
        ):
            collected_events.append(event)
            # Log any progress content
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        logger.info(f"[{agent.name} event text]: {part.text[:100]}")
                        
        # Extract structured output
        output_data = None
        for event in reversed(collected_events):
            if event.output is not None:
                output_data = event.output
                break
                
        # If output was found, return it
        if output_data is not None:
            # ADK already parses it if output_schema was specified, but double check
            if isinstance(output_data, output_schema_class):
                return output_data
            elif isinstance(output_data, dict):
                return output_schema_class.model_validate(output_data)
            elif isinstance(output_data, str):
                import json
                try:
                    cleaned_str = output_data.strip()
                    if cleaned_str.startswith("```json"):
                        cleaned_str = cleaned_str.split("```json")[1].split("```")[0].strip()
                    elif cleaned_str.startswith("```"):
                        cleaned_str = cleaned_str.split("```")[1].split("```")[0].strip()
                    return output_schema_class.model_validate_json(cleaned_str)
                except Exception as parse_err:
                    logger.error(f"Failed to parse string output from {agent.name}: {parse_err}. Raw: {output_data}")
                    
        raise ValueError(f"Agent '{agent.name}' did not produce a valid output of type {output_schema_class.__name__}")
        
    except Exception as e:
        logger.error(f"Execution failed for agent '{agent.name}': {e}. Returning fallback default output.")
        
        # Create a graceful default fallback
        if output_schema_class.__name__ == "IndicatorOutput":
            # Extract ticker from message if possible
            ticker = "UNKNOWN"
            for word in user_message.split():
                if len(word) == 3 and word.isupper():
                    ticker = word
                    break
            # Find as_of_date if possible
            as_of_date = "live"
            if "as of" in user_message:
                parts = user_message.split("as of")
                if len(parts) > 1:
                    as_of_date = parts[1].strip()[:10]
                    
            from .schemas import IndicatorOutput
            return IndicatorOutput(
                indicator=agent.description or agent.name,
                ticker=ticker,
                as_of_date=as_of_date,
                signal="neutral",
                confidence=0.5,
                magnitude_estimate="0% over 5 trading days (fallback)",
                reasoning=f"Graceful degradation: Analysis failed due to run error ({str(e)[:60]}). Falling back to neutral.",
                key_evidence=["Data fetch failed or model timed out - System fallback"],
                data_as_of_lag_days=0,
                sources=["System Fallback Database"]
            )
        elif output_schema_class.__name__ == "EnsembleOutput":
            from .schemas import EnsembleOutput
            return EnsembleOutput(
                direction="neutral",
                confidence=0.5,
                magnitude_range="0% over 5 trading days (fallback)",
                ranked_indicators=["clinical_trials", "physician_adoption", "pubmed", "usaspending", "gdelt"],
                indicator_tags={
                    "clinical_trials": "mainstream",
                    "physician_adoption": "mainstream",
                    "pubmed": "mainstream",
                    "usaspending": "mainstream",
                    "gdelt": "mainstream"
                },
                uncertainty_statement="Analysis failed. Defaulting to neutral due to internal orchestration errors.",
                synthesized_reasoning="Graceful degradation enabled: failed to aggregate indicators."
            )
        else:
            raise e
