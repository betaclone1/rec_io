"""
Shared pytest fixtures and configuration.
Root conftest.py is used by all tests; put integration-only fixtures in tests/integration/conftest.py.
"""
import os

# Port resolution (get_port / trade_manager module scope) requires a tenant slot. CI and bare
# `pytest tests/unit` shells often have none set — default before any backend import at collection.
_u = (os.environ.get("REC_USER_NO") or os.environ.get("REC_POOL_USER_NUMBER") or "").strip()
_schema = (os.environ.get("REC_DEFAULT_USER_SCHEMA") or "").strip()
if not _u and not _schema:
    os.environ.setdefault("REC_USER_NO", "0001")

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no DB, no external API).")
    config.addinivalue_line("markers", "integration: Integration tests (DB, API, or multi-component).")


@pytest.fixture(scope="session")
def project_root():
    """Project root directory (repo root)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
