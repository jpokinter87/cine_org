"""
Tests unitaires pour le module auto_validator.

Vérifie _filter_by_episode_count_compatibility :
auto-validation quand un seul candidat TVDB a un nombre d'épisodes compatible.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.cli.auto_validator import _filter_by_episode_count_compatibility
from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile


def _make_pending(
    filename: str,
    candidates: list[dict],
) -> PendingValidation:
    """Crée un PendingValidation de test."""
    return PendingValidation(
        id="test-id",
        video_file=VideoFile(
            path=Path("/downloads/series") / filename,
            filename=filename,
        ),
        candidates=candidates,
        validation_status=ValidationStatus.PENDING,
    )


def _make_candidate(id: str, title: str, score: float = 67.0) -> dict:
    """Crée un dict candidat."""
    return {
        "id": id,
        "title": title,
        "score": score,
        "source": "tvdb",
    }


class TestFilterByEpisodeCountCompatibility:
    """Tests pour _filter_by_episode_count_compatibility."""

    @pytest.mark.asyncio
    async def test_auto_validates_single_compatible_candidate(self):
        """Auto-valide quand un seul candidat a un episode count compatible."""
        tvdb_client = MagicMock()

        async def mock_count(series_id, season):
            if series_id == "111":
                return 22  # compatible (episode 10 <= 22)
            return 5  # incompatible (episode 10 > 5)

        tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        pending = _make_pending("serie.s03e10.mkv", [
            _make_candidate("111", "Serie A", score=70.0),
            _make_candidate("222", "Serie B", score=65.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], tvdb_client
        )

        assert len(validated) == 1
        assert len(remaining) == 0
        assert validated[0] is pending
        # Vérifie que le candidat compatible est marqué
        assert validated[0]._episode_validated_candidate["id"] == "111"

    @pytest.mark.asyncio
    async def test_no_auto_validation_when_multiple_compatible(self):
        """Pas d'auto-validation quand plusieurs candidats sont compatibles."""
        tvdb_client = MagicMock()
        tvdb_client.get_season_episode_count = AsyncMock(return_value=22)

        pending = _make_pending("serie.s03e10.mkv", [
            _make_candidate("111", "Serie A", score=70.0),
            _make_candidate("222", "Serie B", score=65.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], tvdb_client
        )

        assert len(validated) == 0
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_no_auto_validation_when_score_below_threshold(self):
        """Pas d'auto-validation quand le score du candidat compatible est < 60%."""
        tvdb_client = MagicMock()

        async def mock_count(series_id, season):
            if series_id == "111":
                return 22  # compatible
            return 5  # incompatible

        tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        pending = _make_pending("serie.s03e10.mkv", [
            _make_candidate("111", "Serie A", score=50.0),  # score trop bas
            _make_candidate("222", "Serie B", score=45.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], tvdb_client
        )

        assert len(validated) == 0
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_no_tvdb_client_returns_all_remaining(self):
        """Sans tvdb_client, tous les fichiers restent en remaining."""
        pending = _make_pending("serie.s03e10.mkv", [
            _make_candidate("111", "Serie A", score=70.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], None
        )

        assert len(validated) == 0
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_skips_movie_candidates(self):
        """Ignore les candidats TMDB (films)."""
        tvdb_client = MagicMock()
        tvdb_client.get_season_episode_count = AsyncMock(return_value=22)

        pending = _make_pending("serie.s03e10.mkv", [
            {"id": "111", "title": "Film A", "score": 70.0, "source": "tmdb"},
            _make_candidate("222", "Serie B", score=65.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], tvdb_client
        )

        # Un seul candidat TVDB compatible (222 avec 22 episodes)
        assert len(validated) == 1
        assert validated[0]._episode_validated_candidate["id"] == "222"

    @pytest.mark.asyncio
    async def test_no_season_episode_in_filename(self):
        """Fichiers sans info saison/episode restent en remaining."""
        tvdb_client = MagicMock()
        tvdb_client.get_season_episode_count = AsyncMock(return_value=22)

        pending = _make_pending("documentaire.mkv", [
            _make_candidate("111", "Serie A", score=70.0),
        ])

        validated, remaining = await _filter_by_episode_count_compatibility(
            [pending], tvdb_client
        )

        assert len(validated) == 0
        assert len(remaining) == 1
