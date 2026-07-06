MedTech Stock Analyst: Multi-Agent AI for Evidence-Based Investment Signals

Turning Public Healthcare Data into Actionable Stock Intelligence with Google ADK and MCP

The Problem

Publicly traded healthcare and MedTech companies are among the most data rich sectors in the world. Clinical trials are registered with the FDA. Prescriber patterns are published by CMS. Scientific research flows through PubMed. Government contracts are tracked by USAspending.gov. News sentiment is captured in real time by GDELT. And price data is freely available through Yahoo Finance.

The paradox is that this data is scattered across dozens of independent government agencies, academic databases, and media sources. No single investor, analyst, or fund has the bandwidth to continuously monitor all of these signals simultaneously for multiple companies. As a result, material information often goes unnoticed by the market for days or weeks, creating both risk and opportunity.

Existing stock analysis tools focus on traditional financial metrics: earnings reports, P/E ratios, and technical indicators. They almost entirely ignore the rich alternative data streams that are unique to the healthcare sector. A clinical trial termination, a surge in physician prescriptions, or a major government contract award can move a stock long before any quarterly filing captures it.

The central question this project addresses is: can we build a multi-agent AI system that continuously monitors these disparate data sources, synthesizes them into a single evidence-backed signal, and surfaces insights that would otherwise remain hidden?

Why Agents?

This problem is a natural fit for a multi-agent architecture for several reasons.

First, the data sources are fundamentally different in structure and access method. ClinicalTrials.gov requires querying trial registrations and analyzing status codes. CMS data requires parsing Medicare Part D prescriber files for year over year trends. PubMed requires searching publication databases and measuring momentum. USAspending requires filtering government contract awards. GDELT requires analyzing global news article tone. Each of these demands a specialized approach to data retrieval and analysis.

Second, the synthesis step requires reasoning across domains. A clinical trial setback might be offset by a strong government contract win. Physician adoption trends that disagree with headline sentiment might represent an under covered opportunity. Combining these signals into a coherent prediction requires nuanced weighting that is well suited to an LLM based ensemble agent.

Third, the system needs to be extensible. Adding a new data source or indicator should not require rewriting the entire pipeline. The multi-agent architecture with MCP (Model Context Protocol) servers allows new capabilities to be plugged in as independent tools.

Architecture

The system is built on Google's Agent Development Kit (ADK) and uses a team of five specialized indicator agents, each backed by at least one MCP server, plus an ensemble agent and a report writer agent.

The Clinical Trial Execution Agent queries ClinicalTrials.gov to analyze trial statuses, completion rates, terminations, and timeline slippage for a given company. It produces a bullish, bearish, or neutral signal with supporting evidence.

The Physician Adoption Signals Agent analyzes CMS Medicare Part D Prescriber Public Use Files to measure year over year growth in prescribers and claims for a company's key drugs.

The Scientific Publication Momentum Agent searches PubMed to track publication volume trends for a company's key drugs, measuring acceleration or deceleration in research output.

The Government Procurement Agent queries USAspending.gov to identify and size government contract awards, measuring their significance relative to company revenue.

The Headline Sentiment Agent analyzes GDELT global news data to measure mainstream media sentiment and coverage volume.

The Ensemble Agent receives all five indicator outputs and synthesizes them into a single weighted prediction using a quantitative algorithm: each indicator votes bullish with a value of plus one, neutral with zero, or bearish with minus one, weighted by its confidence score, with a threshold of plus or minus 0.3 for direction.

The Report Writer Agent generates a comprehensive markdown report combining the ensemble prediction with individual indicator breakdowns, evidence summaries, and an uncertainty disclaimer.

Six MCP servers provide data access to the agents: ClinicalTrials.gov, CMS Prescriber Data, PubMed, USAspending.gov, GDELT News Sentiment, and yfinance Price Data. All MCP servers are free public APIs with no API key requirements, making the system accessible to anyone.

The orchestrator coordinates execution in three phases. In Phase 1, all five indicator agents run in parallel, each independently querying their MCP servers and producing structured IndicatorOutput objects. In Phase 2, the ensemble agent receives all five outputs and produces a single EnsembleOutput with direction, confidence, magnitude range, and ranked indicators. In Phase 3, the report writer agent generates a formatted markdown report.

A FastAPI frontend server exposes a REST API with two endpoints: one for running analyses and one for checking authentication status. The frontend is a dark themed single page application with ticker selection, live and backtest mode toggles, a date picker, and an interactive results display including a dual axis price and volume chart.

Security Architecture

Security was a first class design consideration throughout the project.

API keys are never hardcoded in source code. The environment file is gitignored at the repository level. On the backend, the key is read from the environment variable within each request context and discarded after the request completes.

MCP server environment variable access is restricted through an allowlist approach. Both the MCP tools module and the MCP client utility explicitly define which environment variables the MCP subprocesses are permitted to access, preventing any MCP server from leaking sensitive credentials.

Error messages returned to the client are sanitized to avoid exposing internal paths, server configuration details, or stack traces. LLM agents gracefully degrade to neutral fallback signals with a confidence of 0.3 when authentication fails, ensuring the system returns a response even without working credentials.

For authentication, the system supports two modes. Vertex AI mode is the primary path and uses Google Cloud application default credentials with free trial credits. Developer API mode is the fallback and uses a Gemini API key set in the environment file.

Technical Implementation

The codebase is organized into a modular structure with clear separation of concerns. The agents directory contains the individual agent implementations, each in its own subdirectory with an agent definition and run function. The ensemble agent sits in the ensemble ranking directory. The report writer has its own directory. The orchestrator coordinates the full pipeline.

The schemas module defines the Pydantic models used throughout the system, including IndicatorOutput and EnsembleOutput with strict validation. A schema modification strips additional properties from the JSON schema to ensure compatibility with the Gemini Developer API.

The runner helper provides a generic run agent function that handles session creation, message passing, and structured output extraction for any ADK agent, reducing boilerplate across agent implementations.

The MCP client utility provides a reusable client class that manages subprocess lifecycle for MCP servers, with environment variable allowlisting and proper cleanup on exit.

The frontend server is a FastAPI application that serves the frontend and exposes the API. It includes a secure key handling context manager and CORS middleware for local development.

The test suite contains 42 tests covering schema validation, MCP lookahead lag filters for all six data sources, price data formatting, backtest scoring, and graceful degradation. Thirty tests pass and twelve are LLM dependent, skipped when no API key is available.

Project Journey

This project went through several iterations before reaching its current form.

The initial prototype used the Gemini Developer API with a free tier key. It worked on the first run, but quickly hit a wall with persistent 429 rate limits and quota exhaustion because the free tier allows only 20 requests per day and each full analysis requires 10 to 12 LLM calls. Every test run consumed nearly the entire daily budget.

The solution was to switch to Vertex AI with Google Cloud authentication. This moved the project from a prepaid API key model to a Cloud billing account with free trial credits, removing the rate limit bottleneck entirely. The switch required changes across the codebase: the frontend no longer needed an API key settings panel, the backend context manager needed a no-operation path for Vertex mode, and the test suite needed to detect which auth mode was active.

Another challenge was schema compatibility. The Gemini Developer API rejected the EnsembleOutput Pydantic model because it contained a dictionary field with dynamic keys, which the API interpreted as requiring additional properties support. The fix was a recursive schema modification function that strips additional properties from the generated JSON schema without changing the Python model itself, preserving backward compatibility with existing code.

The frontend also evolved significantly. The initial price display was raw JSON text. We experimented with a dual chart layout showing price and volume side by side, then settled on a single combined chart with dual Y axes that overlays the price line on top of volume bars. The report rendering went through a similar cycle: from plain monospace text to a full HTML rendered document with styled signal badges and key value labels, and back to monospace for simplicity. The lesson was that for a technical analysis tool, clear data often speaks louder than visual polish.

The most important architectural decision was the data lag model. Each data source has a different release delay: CMS prescriber data lags by 21 months, PubMed by 14 days, while ClinicalTrials.gov and GDELT are near real time. Getting the lookahead bias wrong would make backtest results meaningless. Implementing release lag filtering for all six MCP servers was tedious but essential work that directly determined whether the validation results could be trusted.

Results and Validation

The system has been validated through both live analysis and historical backtesting.

Live analysis on Novo Nordisk returned a bullish signal with 80 percent confidence driven by strong clinical trial execution, accelerating scientific publication momentum, and rapid physician adoption of Ozempic and Wegovy. The system correctly identified that these positive signals were under covered by mainstream news.

Backtesting on historical dates provides a mechanism for ongoing validation. The system correctly predicted Amgen as range bound in September 2023, where government procurement bullishness was offset by declining physician adoption of Enbrel, resulting in a neutral overall signal with the price moving up 1.95 percent over the next five trading days.

Each indicator output includes a confidence score, magnitude estimate, detailed reasoning, key evidence with source citations, and a data lag measurement that accounts for the real world release delay of each data source. This transparency allows users to assess the quality and timeliness of each signal independently.

Built With

The system was built with Google ADK for multi-agent orchestration, Gemini 2.5 Flash as the underlying LLM, MCP for standardized data source access, FastAPI for the backend server, Chart.js for interactive price and volume visualization, Pydantic for data validation and schema management, and six free public API data sources.

Conclusion

The MedTech Stock Analyst demonstrates that a multi-agent AI system can effectively aggregate and synthesize diverse public data sources into actionable investment signals. By combining the Google ADK framework with MCP based data access, the system achieves a modular architecture where specialized agents each own a domain and an ensemble agent reasons across them.

The approach is particularly suited to the healthcare sector, where regulatory filings, government datasets, and scientific publications create a uniquely rich alternative data environment. The same architecture could be adapted to other sectors by swapping the MCP server implementations.

The project is fully open source, documented, and deployable to Google Cloud Run, making it accessible as a reference implementation for anyone building multi-agent systems on Google ADK.

Track: Agents for Business

Key Concepts Demonstrated: Multi-agent system with ADK, MCP Servers, Security features
