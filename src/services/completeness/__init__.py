"""Service de surveillance de la complétude des séries TV."""

from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)
from src.services.completeness.dataclasses import (
    CompletenessResult,
    MissingEpisode,
)

__all__ = [
    "CompletenessChecker",
    "CompletenessResult",
    "MissingEpisode",
    "check_series_model",
]
