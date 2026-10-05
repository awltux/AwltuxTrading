"""Ingest layer: turn provider responses into stored, provenance-tagged rows.

Everything here is a pure function of (session, provider) so it can be tested
against recorded fixtures without the network. No ingest function computes an
opinion -- it normalises, deduplicates and stores, and leaves interpretation to
``analysis`` and ``decision``.
"""
