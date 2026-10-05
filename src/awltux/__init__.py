"""AwltuxTrading -- a background share valuation and sentiment advisor.

Layered so that each stage is separately testable and separately trustworthy:

``providers``  fetch from the outside world, with rate limits and caching
``ingest``     normalise into the database, with provenance
``analysis``   deterministic maths -- this is where every number is produced
``llm``        DeepSeek investigation and summarisation, with source spans
``decision``   JEV (with DeepSeek/offline fallback) answers + composite + gate
``audit``      the immutable ledger that makes a decision reproducible
``web``        the dashboard, served from FastAPI
"""

__version__ = "0.1.0"
