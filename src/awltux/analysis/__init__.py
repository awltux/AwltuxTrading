"""Analysis layer: deterministic computation over stored data.

Everything in this package produces numbers from inputs that are already in the
database. No network calls happen here (FX rates are fetched by a provider and
cached), which keeps a valuation run reproducible from stored inputs alone.
"""
