"""Basic unit test to verify project structure and pytest discovery."""
import os
import pytest


def _project_root():
    """Repo root: tests/unit/test_*.py -> go up to repo."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.unit
def test_project_root_has_backend():
    """Project root should contain backend/."""
    root = _project_root()
    assert os.path.isdir(os.path.join(root, "backend")), "backend/ not found"


@pytest.mark.unit
def test_project_root_has_scripts():
    """Project root should contain scripts/."""
    root = _project_root()
    assert os.path.isdir(os.path.join(root, "scripts")), "scripts/ not found"


@pytest.mark.unit
def test_backend_has_main():
    """backend/main.py should exist."""
    root = _project_root()
    assert os.path.isfile(os.path.join(root, "backend", "main.py")), "backend/main.py not found"
