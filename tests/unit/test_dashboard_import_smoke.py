"""Smoke test: confirm the top-level dashboard/ package is importable from pytest."""

import pytest


@pytest.mark.unit
def test_dashboard_queries_importable():
    import dashboard.queries  # noqa: F401
