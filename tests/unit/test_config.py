"""Tests des paramètres pydantic Settings (src.config)."""

import pytest
from pydantic import ValidationError

from src.config import Settings


class TestShortFilmDurationThreshold:
    """Le seuil de durée des courts-métrages doit être configurable et borné."""

    def test_default_is_900_seconds(self) -> None:
        settings = Settings()
        assert settings.short_film_duration_threshold_seconds == 900

    def test_can_be_overridden(self) -> None:
        settings = Settings(short_film_duration_threshold_seconds=1200)
        assert settings.short_film_duration_threshold_seconds == 1200

    def test_rejects_value_below_minimum(self) -> None:
        with pytest.raises(ValidationError):
            Settings(short_film_duration_threshold_seconds=30)
