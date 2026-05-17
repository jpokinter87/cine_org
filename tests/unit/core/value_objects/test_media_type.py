"""Tests de l'enum MediaType."""

from src.core.value_objects import MediaType


class TestMediaTypeEnum:
    """Vérifie la présence des valeurs attendues dans MediaType."""

    def test_movie_exists(self) -> None:
        assert MediaType.MOVIE.value == "movie"

    def test_series_exists(self) -> None:
        assert MediaType.SERIES.value == "series"

    def test_unknown_exists(self) -> None:
        assert MediaType.UNKNOWN.value == "unknown"

    def test_short_exists(self) -> None:
        """Le type court-métrage doit être disponible pour la classification."""
        assert MediaType.SHORT.value == "short"
