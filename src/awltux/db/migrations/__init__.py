"""Alembic migration environment.

Present as a package so the migrations directory (``env.py``, ``versions/`` and
the template) is installed alongside the rest of ``awltux`` rather than only
existing in a source checkout. Without this, ``pip install .`` would leave the
migrations behind and a deployed container could not migrate its own database --
which is exactly what happened.
"""
