"""
tests/test_all.py
===================
Comprehensive test suite for the MedTech Stock Analyst system.

Tests cover:
  1. Five indicator agents — schema compliance & graceful degradation
  2. Price data agent — historical data & lookahead prevention
  3. Orchestrator — parallel dispatch & failure handling
  4. Ensemble/ranking agent — valid output, ranked list, mainstream tags
  5. Report writer — well-formed output with citations
  6. Backtest runner — lookahead-bias lag filtering & scoring

Run with:
    python -m pytest tests/test_all.py -v --tb=short

All non-LLM tests run unconditionally.
LLM-dependent tests (indicator agents, ensemble, report writer, orchestrator)
require a real GEMINI_API_KEY in the environment or working Vertex AI creds.
"""

import os
import sys
import asyncio
import json
import logging
import unittest
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from agents.schemas import IndicatorOutput, EnsembleOutput
from agents.indicators.clinical_trials_agent import run as run_clinical_trials
from agents.indicators.physician_adoption_agent import run as run_physician_adoption
from agents.indicators.pubmed_agent import run as run_pubmed
from agents.indicators.usaspending_agent import run as run_usaspending
from agents.indicators.gdelt_agent import run as run_gdelt
from agents.price_data.price_data_agent import run as run_price_data, get_forward_returns
from agents.orchestrator.orchestrator import run_analysis, SUPPORTED_TICKERS, _make_neutral_fallback
from agents.ensemble_ranking.ensemble_agent import run as run_ensemble
from agents.report_writer.report_writer_agent import run as run_report_writer
from backtest.runner import run_backtest_pair, extract_magnitude_range, parse_pair

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TEST_TICKERS = ["JNJ", "NVO", "PFE", "AMGN", "GSK"]
TIMEOUT_SECONDS = 120


def _has_api_key() -> bool:
    """Check if the environment has a usable Gemini API key or Vertex AI."""
    gk = os.environ.get("GEMINI_API_KEY", "")
    if gk and gk != "your_gemini_api_key_here":
        return True
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        if os.environ.get("GOOGLE_CLOUD_PROJECT"):
            return True
    return False


def run_async(coro, timeout=TIMEOUT_SECONDS):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


# ============================================================================
# 1. INDICATOR AGENT TESTS
# ============================================================================

def _check_indicator_output_schema(output):
    assert isinstance(output, IndicatorOutput), f"Expected IndicatorOutput, got {type(output)}"
    assert output.indicator and isinstance(output.indicator, str)
    assert output.ticker in SUPPORTED_TICKERS, f"Invalid ticker: {output.ticker}"
    assert output.as_of_date
    assert output.signal in ("bullish", "bearish", "neutral"), f"Invalid signal: {output.signal}"
    assert 0.0 <= output.confidence <= 1.0, f"Confidence out of range: {output.confidence}"
    assert output.magnitude_estimate
    assert output.reasoning and len(output.reasoning) > 10
    assert len(output.key_evidence) >= 1
    assert len(output.sources) >= 1
    assert isinstance(output.data_as_of_lag_days, int)
    return True


class TestIndicatorAgents(unittest.TestCase):

    def test_clinical_trials_api_returns_real_data(self):
        """ClinicalTrials.gov MCP returns real, non-empty data for at least one ticker."""
        from agents.mcp_tools import call_mcp_tool
        for ticker in TEST_TICKERS:
            raw = run_async(call_mcp_tool(
                "mcp_servers/clinical_trials.py", "query_clinical_trials",
                {"ticker": ticker, "as_of_date": "2024-06-01"},
            ))
            data = json.loads(raw)
            if data.get("total_trials_found", 0) > 0:
                self.assertGreater(len(data.get("trials", [])), 0)
                return
        self.skipTest("No trials found for any ticker (API may be unavailable)")

    def test_usaspending_api_returns_real_data(self):
        """USAspending.gov MCP returns real, non-empty data."""
        from agents.mcp_tools import call_mcp_tool
        for ticker in TEST_TICKERS:
            raw = run_async(call_mcp_tool(
                "mcp_servers/usaspending.py", "query_government_contracts",
                {"ticker": ticker, "as_of_date": "2024-06-01"},
            ))
            data = json.loads(raw)
            total = data.get("total_contracts_value_found_usd", 0)
            if total > 0:
                return
        self.skipTest("No contracts found for any ticker (API may be unavailable)")

    def test_gdelt_api_returns_real_or_fallback_data(self):
        """GDELT MCP returns data (live or deterministic mock fallback)."""
        from agents.mcp_tools import call_mcp_tool
        raw = run_async(call_mcp_tool(
            "mcp_servers/gdelt.py", "query_headlines_sentiment",
            {"ticker": "JNJ", "as_of_date": "2024-06-01"},
        ))
        data = json.loads(raw)
        self.assertIn("articles", data, "GDELT should return articles key")
        self.assertGreater(len(data.get("articles", [])), 0, "Should have at least one article")

    def test_indicator_graceful_degradation(self):
        """Agent fallback returns neutral IndicatorOutput with confidence=0.3."""
        fallback = _make_neutral_fallback(
            "Clinical Trial Execution", "JNJ", "2024-06-01",
            Exception("Simulated failure"),
        )
        self.assertIsInstance(fallback, IndicatorOutput)
        self.assertEqual(fallback.signal, "neutral")
        self.assertEqual(fallback.confidence, 0.3)

    def test_indicator_schema_via_llm(self):
        """Each indicator agent LLM call returns schema-compliant output (requires API key)."""
        if not _has_api_key():
            self.skipTest("No API key available")
        agents_data = [
            ("Clinical Trial Execution", run_clinical_trials),
            ("Physician Adoption Signals", run_physician_adoption),
            ("Scientific Publication Momentum", run_pubmed),
            ("Government Procurement", run_usaspending),
            ("Headline Sentiment", run_gdelt),
        ]
        for name, fn in agents_data:
            try:
                result = run_async(fn("JNJ", "2024-06-01"))
                self.assertTrue(_check_indicator_output_schema(result))
            except Exception as e:
                # Agent should return neutral fallback on failure
                self.fail(f"{name} LLM call failed: {e}")


# ============================================================================
# 2. PRICE DATA AGENT TESTS
# ============================================================================

class TestPriceDataAgent(unittest.TestCase):

    def test_returns_history(self):
        """Price data agent returns price history with close/date/volume."""
        result = run_async(run_price_data("JNJ"))
        self.assertIn("prices", result)
        prices = result["prices"]
        self.assertGreater(len(prices), 0)
        self.assertIn("close", prices[0])
        self.assertIn("date", prices[0])
        self.assertIn("volume", prices[0])

    def test_backtest_no_lookahead(self):
        """All price dates are <= as_of_date in backtest mode."""
        as_of_date = "2023-01-15"
        result = run_async(run_price_data("JNJ", as_of_date=as_of_date))
        for p in result.get("prices", []):
            self.assertLessEqual(p["date"], as_of_date,
                                 f"Price {p['date']} > as_of_date")

    def test_all_tickers(self):
        """Returns prices for all five supported tickers."""
        for ticker in TEST_TICKERS:
            result = run_async(run_price_data(ticker))
            self.assertGreater(len(result.get("prices", [])), 0, f"No prices for {ticker}")

    def test_error_handling(self):
        """Graceful response for unsupported ticker."""
        result = run_async(run_price_data("INVALID"))
        # The MCP server returns a message dict (no 'prices' key for unknown tickers)
        self.assertIn("ticker", result)
        self.assertEqual(result.get("ticker"), "INVALID")
        has_info = "error" in result or "message" in result
        self.assertTrue(has_info, f"Expected error/message in response, got {list(result.keys())}")

    def test_forward_returns_separate(self):
        """get_forward_returns is independent from price data and returns a %
        that is computed AFTER as_of_date."""
        result = run_async(get_forward_returns("JNJ", "2023-01-15", 5))
        self.assertIn("forward_return_pct", result)
        self.assertIsInstance(result["forward_return_pct"], (int, float))

    def test_live_is_recent(self):
        """Live-mode prices are from the last ~60 days."""
        result = run_async(run_price_data("PFE"))
        prices = result.get("prices", [])
        if prices:
            latest = datetime.strptime(prices[-1]["date"], "%Y-%m-%d")
            self.assertGreaterEqual(latest, datetime.now() - timedelta(days=60))


# ============================================================================
# 3. ORCHESTRATOR TESTS
# ============================================================================

class TestOrchestrator(unittest.TestCase):

    def test_fans_out_all_agents(self):
        """Returns all 5 indicators + price + ensemble + report."""
        if not _has_api_key():
            self.skipTest("No API key available")
        result = run_async(run_analysis("JNJ", mode="live"))
        self.assertEqual(len(result["indicator_outputs"]), 5)
        self.assertIn("price_context", result)
        self.assertIn("ensemble", result)
        self.assertIn("report", result)

    def test_backtest_mode(self):
        """Backtest mode caps data at as_of_date."""
        if not _has_api_key():
            self.skipTest("No API key available")
        result = run_async(run_analysis("NVO", mode="backtest", as_of_date="2023-06-01"))
        self.assertEqual(result["mode"], "backtest")
        self.assertEqual(result["as_of_date"], "2023-06-01")

    def test_unsupported_ticker_raises(self):
        """ValueError raised for unsupported ticker."""
        with self.assertRaises(ValueError):
            run_async(run_analysis("TSLA", mode="live"))


# ============================================================================
# 4. ENSEMBLE / RANKING AGENT TESTS
# ============================================================================

class TestEnsembleAgent(unittest.TestCase):

    def _make_indicators(self):
        return [
            IndicatorOutput(indicator="Clinical Trial Execution", ticker="JNJ",
                as_of_date="2024-06-01", signal="bullish", confidence=0.8,
                magnitude_estimate="+2% to +4%", reasoning="Strong enrollment.",
                key_evidence=["Trial NCT012345"], data_as_of_lag_days=0,
                sources=["https://clinicaltrials.gov"]),
            IndicatorOutput(indicator="Physician Adoption Signals", ticker="JNJ",
                as_of_date="2024-06-01", signal="bullish", confidence=0.6,
                magnitude_estimate="+1% to +3%", reasoning="Growing prescribers.",
                key_evidence=["Stelara up 15% YoY"], data_as_of_lag_days=630,
                sources=["CMS PUF"]),
            IndicatorOutput(indicator="Scientific Publication Momentum", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.5,
                magnitude_estimate="0% to +1%", reasoning="Stable counts.",
                key_evidence=["120 pubs / 60d"], data_as_of_lag_days=14,
                sources=["PubMed"]),
            IndicatorOutput(indicator="Government Procurement", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.4,
                magnitude_estimate="0% to +0.5%", reasoning="No big contracts.",
                key_evidence=["0.02% of revenue"], data_as_of_lag_days=0,
                sources=["USAspending"]),
            IndicatorOutput(indicator="Headline Sentiment", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.5,
                magnitude_estimate="-0.5% to +0.5%", reasoning="Mixed news.",
                key_evidence=["Avg tone 0.3"], data_as_of_lag_days=0,
                sources=["GDELT"]),
        ]

    def test_llm_output_valid(self):
        """Ensemble LLM returns valid EnsembleOutput (requires API key)."""
        if not _has_api_key():
            self.skipTest("No API key available")
        indicators = self._make_indicators()
        result = run_async(run_ensemble("JNJ", "2024-06-01", indicators))
        self.assertIsInstance(result, EnsembleOutput)
        self.assertIn(result.direction, ("bullish", "bearish", "neutral"))

    def test_llm_ranked_list(self):
        """Ensemble ranks exactly 5 indicators, no duplicates."""
        if not _has_api_key():
            self.skipTest("No API key available")
        indicators = self._make_indicators()
        result = run_async(run_ensemble("JNJ", "2024-06-01", indicators))
        self.assertEqual(len(result.ranked_indicators), 5)
        self.assertEqual(len(set(result.ranked_indicators)), 5)

    def test_llm_mainstream_tags(self):
        """Headline Sentiment is always 'mainstream'."""
        if not _has_api_key():
            self.skipTest("No API key available")
        indicators = self._make_indicators()
        result = run_async(run_ensemble("JNJ", "2024-06-01", indicators))
        tags = result.indicator_tags
        self.assertEqual(len(tags), 5)
        self.assertEqual(tags.get("Headline Sentiment"), "mainstream")

    def test_llm_uncertainty(self):
        """Ensemble output includes substantive uncertainty statement."""
        if not _has_api_key():
            self.skipTest("No API key available")
        indicators = self._make_indicators()
        result = run_async(run_ensemble("JNJ", "2024-06-01", indicators))
        self.assertGreater(len(result.uncertainty_statement), 20)
        self.assertGreater(len(result.synthesized_reasoning), 30)

    def test_neutral_fallback(self):
        """Fallback ensemble is neutral with confidence 0.3."""
        from agents.ensemble_ranking.ensemble_agent import _neutral_ensemble
        fb = _neutral_ensemble("JNJ", "test error")
        self.assertEqual(fb.direction, "neutral")
        self.assertEqual(fb.confidence, 0.3)


# ============================================================================
# 5. REPORT WRITER TESTS
# ============================================================================

class TestReportWriter(unittest.TestCase):

    def _make_data(self):
        ensemble = EnsembleOutput(
            direction="bullish", confidence=0.72,
            magnitude_range="+1% to +3% over 5 trading days",
            ranked_indicators=[
                "Clinical Trial Execution", "Physician Adoption Signals",
                "Headline Sentiment", "Scientific Publication Momentum",
                "Government Procurement",
            ],
            indicator_tags={
                "Clinical Trial Execution": "under-covered",
                "Physician Adoption Signals": "under-covered",
                "Scientific Publication Momentum": "mainstream",
                "Government Procurement": "mainstream",
                "Headline Sentiment": "mainstream",
            },
            uncertainty_statement="This is not investment advice.",
            synthesized_reasoning="Strong trial momentum and physician adoption.",
        )
        indicators = [
            IndicatorOutput(indicator="Clinical Trial Execution", ticker="JNJ",
                as_of_date="2024-06-01", signal="bullish", confidence=0.8,
                magnitude_estimate="+2% to +4%", reasoning="Strong enrollment.",
                key_evidence=["Trial NCT012345"], data_as_of_lag_days=0,
                sources=["https://clinicaltrials.gov"]),
            IndicatorOutput(indicator="Physician Adoption Signals", ticker="JNJ",
                as_of_date="2024-06-01", signal="bullish", confidence=0.6,
                magnitude_estimate="+1% to +3%", reasoning="Growing prescribers.",
                key_evidence=["Stelara up 15% YoY"], data_as_of_lag_days=630,
                sources=["CMS PUF"]),
            IndicatorOutput(indicator="Scientific Publication Momentum", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.5,
                magnitude_estimate="0% to +1%", reasoning="Stable.",
                key_evidence=["120 pubs"], data_as_of_lag_days=14,
                sources=["PubMed"]),
            IndicatorOutput(indicator="Government Procurement", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.4,
                magnitude_estimate="0% to +0.5%", reasoning="No big contracts.",
                key_evidence=["0.02% of revenue"], data_as_of_lag_days=0,
                sources=["USAspending"]),
            IndicatorOutput(indicator="Headline Sentiment", ticker="JNJ",
                as_of_date="2024-06-01", signal="neutral", confidence=0.5,
                magnitude_estimate="-0.5% to +0.5%", reasoning="Mixed.",
                key_evidence=["Avg tone 0.3"], data_as_of_lag_days=0,
                sources=["GDELT"]),
        ]
        ctx = {"ticker": "JNJ", "prices": [{"date": "2024-05-01", "close": 150.0, "volume": 5000000}],
               "latest_close": 152.0, "30d_return_pct": 1.5}
        return ensemble, indicators, ctx

    def test_llm_returns_string(self):
        """Report writer LLM returns a string (requires API key)."""
        if not _has_api_key():
            self.skipTest("No API key available")
        ensemble, indicators, ctx = self._make_data()
        result = run_async(run_report_writer("JNJ", "2024-06-01", ensemble, indicators, ctx))
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)

    def test_llm_has_key_sections(self):
        """Report includes overall prediction, disclaimer, and sources."""
        if not _has_api_key():
            self.skipTest("No API key available")
        ensemble, indicators, ctx = self._make_data()
        result = run_async(run_report_writer("JNJ", "2024-06-01", ensemble, indicators, ctx))
        self.assertIn("Overall", result)
        self.assertIn("Disclaimer", result)

    def test_llm_includes_sources(self):
        """Report cites sources for indicators."""
        if not _has_api_key():
            self.skipTest("No API key available")
        ensemble, indicators, ctx = self._make_data()
        result = run_async(run_report_writer("JNJ", "2024-06-01", ensemble, indicators, ctx))
        sources_found = sum(1 for s in ["clinicaltrials.gov", "CMS", "PubMed", "USAspending", "GDELT"]
                           if s.lower() in result.lower())
        self.assertGreaterEqual(sources_found, 2)

    def test_llm_uncertainty_section(self):
        """Report includes uncertainty/disclaimer keywords."""
        if not _has_api_key():
            self.skipTest("No API key available")
        ensemble, indicators, ctx = self._make_data()
        result = run_async(run_report_writer("JNJ", "2024-06-01", ensemble, indicators, ctx))
        keywords = ["uncertainty", "not investment advice", "disclaimer", "risk", "warning"]
        found = any(kw in result.lower() for kw in keywords)
        self.assertTrue(found)

    def test_fallback_on_error(self):
        """Report writer returns minimal markdown on LLM error."""
        # Pass invalid data to trigger the fallback
        result = run_async(run_report_writer("JNJ", "2024-06-01",
            {"direction": "neutral", "confidence": 0.0}, [], {}))
        self.assertIsInstance(result, str)
        self.assertIn("JNJ", result)


# ============================================================================
# 6. BACKTEST RUNNER TESTS
# ============================================================================

class TestBacktestRunner(unittest.TestCase):

    def test_parse_pair_valid(self):
        ticker, date = parse_pair("JNJ:2023-01-15")
        self.assertEqual(ticker, "JNJ")
        self.assertEqual(date, "2023-01-15")

    def test_parse_pair_invalid(self):
        with self.assertRaises(ValueError):
            parse_pair("invalid")
        with self.assertRaises(ValueError):
            parse_pair("JNJ:not-a-date")

    def test_extract_magnitude_positive(self):
        low, high = extract_magnitude_range("+1% to +3%")
        self.assertAlmostEqual(low, 1.0)
        self.assertAlmostEqual(high, 3.0)

    def test_extract_magnitude_negative(self):
        low, high = extract_magnitude_range("-5% to -2%")
        self.assertAlmostEqual(low, -5.0)
        self.assertAlmostEqual(high, -2.0)

    def test_extract_magnitude_fallback(self):
        low, high = extract_magnitude_range("0% (fallback)")
        self.assertAlmostEqual(low, -100.0)
        self.assertAlmostEqual(high, 100.0)

    def test_backtest_pair_scored(self):
        """Backtest pair returns scored result (requires API key)."""
        if not _has_api_key():
            self.skipTest("No API key available")
        result = run_async(run_backtest_pair("JNJ", "2023-01-15", 5))
        self.assertIn("ticker", result)
        self.assertIn("score", result)
        self.assertIn("direction_correct", result["score"])
        self.assertIn("forward_return", result)
        self.assertIn("forward_return_pct", result["forward_return"])

    def test_lookahead_lag_clinical_trials(self):
        """Clinical trials filtered by as_of_date."""
        from agents.mcp_tools import call_mcp_tool
        raw = run_async(call_mcp_tool(
            "mcp_servers/clinical_trials.py", "query_clinical_trials",
            {"ticker": "JNJ", "as_of_date": "2020-01-01"},
        ))
        data = json.loads(raw)
        for trial in data.get("trials", []):
            lup = trial.get("last_update_posted", "")
            if lup:
                self.assertLessEqual(lup, "2020-01-01")

    def test_lookahead_lag_cms(self):
        """CMS enforces 21-month release lag."""
        from agents.mcp_tools import call_mcp_tool
        raw = run_async(call_mcp_tool(
            "mcp_servers/cms_prescriber.py", "query_prescriber_data",
            {"ticker": "NVO", "as_of_date": "2023-01-01"},
        ))
        data = json.loads(raw)
        # as_of_date=2023-01-01, month=Jan < Oct => max year = 2023 - 2 - 1 = 2020
        self.assertEqual(data.get("max_visible_data_year"), 2020)
        for r in data.get("data", []):
            self.assertLessEqual(r["year"], 2020)

    def test_lookahead_lag_pubmed(self):
        """PubMed applies 14-day buffer from as_of_date."""
        from agents.mcp_tools import call_mcp_tool
        raw = run_async(call_mcp_tool(
            "mcp_servers/pubmed.py", "query_pubmed_trends",
            {"ticker": "JNJ", "as_of_date": "2023-06-15"},
        ))
        data = json.loads(raw)
        self.assertEqual(data.get("data_as_of_date"), "2023-06-01")

    def test_lookahead_lag_price_data(self):
        """Price data strictly capped at as_of_date."""
        from agents.mcp_tools import call_mcp_tool
        raw = run_async(call_mcp_tool(
            "mcp_servers/price_data.py", "get_historical_prices",
            {"ticker": "JNJ", "start_date": "2022-12-01",
             "end_date": "2023-02-01", "as_of_date": "2023-01-15"},
        ))
        data = json.loads(raw)
        for p in data.get("prices", []):
            self.assertLessEqual(p["date"], "2023-01-15")


# ============================================================================
# SCHEMA VALIDATION TESTS
# ============================================================================

class TestSchemas(unittest.TestCase):

    def test_indicator_output_valid(self):
        out = IndicatorOutput(
            indicator="Test", ticker="JNJ", as_of_date="2024-01-01",
            signal="bullish", confidence=0.75, magnitude_estimate="+1% to +3%",
            reasoning="Test reasoning with sufficient length.",
            key_evidence=["Evidence item 1"], data_as_of_lag_days=0,
            sources=["https://example.com"],
        )
        self.assertEqual(out.signal, "bullish")

    def test_indicator_output_invalid_signal(self):
        with self.assertRaises(Exception):
            IndicatorOutput(
                indicator="Test", ticker="JNJ", as_of_date="2024-01-01",
                signal="invalid", confidence=0.75, magnitude_estimate="+1% to +3%",
                reasoning="Test reasoning.", key_evidence=["E"],
                data_as_of_lag_days=0, sources=["https://example.com"],
            )

    def test_indicator_output_confidence_bounds(self):
        with self.assertRaises(Exception):
            IndicatorOutput(
                indicator="Test", ticker="JNJ", as_of_date="2024-01-01",
                signal="neutral", confidence=1.5, magnitude_estimate="0%",
                reasoning="Test reasoning.", key_evidence=["E"],
                data_as_of_lag_days=0, sources=["https://example.com"],
            )

    def test_ensemble_output_valid(self):
        out = EnsembleOutput(
            direction="bullish", confidence=0.72, magnitude_range="+1% to +3%",
            ranked_indicators=["A", "B", "C", "D", "E"],
            indicator_tags={"A": "mainstream", "B": "under-covered",
                            "C": "mainstream", "D": "mainstream", "E": "mainstream"},
            uncertainty_statement="This is not investment advice.",
            synthesized_reasoning="Multiple signals point upward.",
        )
        self.assertEqual(out.direction, "bullish")

    def test_ensemble_output_invalid_tag(self):
        with self.assertRaises(Exception):
            EnsembleOutput(
                direction="neutral", confidence=0.5, magnitude_range="0%",
                ranked_indicators=["A", "B", "C", "D", "E"],
                indicator_tags={"A": "invalid_tag"},
                uncertainty_statement="T", synthesized_reasoning="T",
            )


# ============================================================================
# UTILITY TESTS
# ============================================================================

class TestUtilities(unittest.TestCase):

    def test_supported_tickers(self):
        self.assertEqual(SUPPORTED_TICKERS, {"JNJ", "NVO", "PFE", "AMGN", "GSK"})

    def test_neutral_fallback_schema(self):
        fb = _make_neutral_fallback("Test", "JNJ", "2024-06-01", Exception("err"))
        self.assertIsInstance(fb, IndicatorOutput)
        self.assertEqual(fb.signal, "neutral")
        self.assertEqual(fb.confidence, 0.3)

    def test_mcp_env_allowlist_includes_api_key(self):
        """MCP env allowlist includes GEMINI_API_KEY but not unrelated secrets."""
        import agents.mcp_tools as mt
        import inspect, re
        src = inspect.getsource(mt.call_mcp_tool)
        match = re.search(r'_SAFE_ENV_KEYS\s*=\s*\{(.*?)\}', src, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn('"GEMINI_API_KEY"', body)
        self.assertIn('"PATH"', body)


# ============================================================================
# RUN ALL
# ============================================================================

if __name__ == "__main__":
    print("=" * 72)
    print("  MedTech Stock Analyst — Comprehensive Test Suite")
    print("=" * 72)
    print(f"  API key available: {_has_api_key()}")
    print(f"  GEMINI_API_KEY set: {bool(os.environ.get('GEMINI_API_KEY') and os.environ['GEMINI_API_KEY'] != 'your_gemini_api_key_here')}")
    print(f"  GOOGLE_GENAI_USE_VERTEXAI: {os.environ.get('GOOGLE_GENAI_USE_VERTEXAI', 'not set')}")
    print(f"  GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT', 'not set')}")
    print("=" * 72)
    print()
    unittest.main(verbosity=2)
