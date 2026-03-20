"""
Shared pytest fixtures and configuration.
Root conftest.py is used by all tests; put integration-only fixtures in tests/integration/conftest.py.
"""
import os
import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no DB, no external API).")
    config.addinivalue_line("markers", "integration: Integration tests (DB, API, or multi-component).")


@pytest.fixture(scope="session")
def project_root():
    """Project root directory (repo root)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
