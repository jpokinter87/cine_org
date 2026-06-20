"""Tests du helper de version (source unique de vérité)."""

import re
import tomllib
from pathlib import Path

from src.version import get_version

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_get_version_matches_pyproject() -> None:
    """get_version() renvoie exactement la version déclarée dans pyproject.toml."""
    with open(_PYPROJECT, "rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    assert get_version() == expected


def test_get_version_is_semver() -> None:
    """La version respecte le format MAJOR.MINOR.PATCH."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", get_version())
