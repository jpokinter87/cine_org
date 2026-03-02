"""
Tests unitaires pour la cascade série dans les routes web de validation.

Vérifie :
- _auto_validate_series_episodes : cascade par candidat existant
- _auto_validate_series_episodes : fallback par titre guessit (candidats vides)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult
from src.web.routes.validation import _auto_validate_series_episodes


def _make_pending(
    id: str,
    filename: str,
    candidates: list[dict],
) -> PendingValidation:
    """Crée un PendingValidation de test."""
    return PendingValidation(
        id=id,
        video_file=VideoFile(path=Path("/downloads/series") / filename),
        candidates=candidates,
        validation_status=ValidationStatus.PENDING,
    )


def _make_candidate_dict(id: str, title: str, score: float = 67.0) -> dict:
    return {"id": id, "title": title, "score": score, "source": "tvdb"}


class TestCascadeSeriesWeb:
    """Tests pour _auto_validate_series_episodes (route web)."""

    @pytest.fixture
    def service(self):
        svc = MagicMock()
        svc.validate_candidate = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_cascade_with_matching_candidates(self, service):
        """Cas normal : même candidat dans la liste des autres épisodes."""
        candidate_dict = _make_candidate_dict("tvdb-123", "Ma Série")
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [candidate_dict])
        other = _make_pending("2", "Ma.Serie.S01E02.mkv", [candidate_dict])

        service.list_pending.return_value = [pending, other]
        selected = SearchResult(id="tvdb-123", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 1
        service.validate_candidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_cascade_fallback_guessit_title(self, service):
        """Fallback : aucun candidat, mais même titre guessit → cascade."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        other_e02 = _make_pending("2", "Ma.Serie.S01E02.mkv", [])
        other_e03 = _make_pending("3", "Ma.Serie.S01E03.mkv", [])

        service.list_pending.return_value = [pending, other_e02, other_e03]
        selected = SearchResult(id="tvdb-999", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 2
        assert service.validate_candidate.call_count == 2

    @pytest.mark.asyncio
    async def test_no_cascade_different_series_no_candidates(self, service):
        """Pas de cascade si les titres guessit diffèrent (sans candidats)."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        other = _make_pending("2", "Autre.Show.S01E01.mkv", [])

        service.list_pending.return_value = [pending, other]
        selected = SearchResult(id="tvdb-999", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 0
        service.validate_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_cascade_when_candidates_exist_but_no_match(self, service):
        """Pas de fallback guessit si l'épisode a des candidats (non-vides)."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        other = _make_pending("2", "Ma.Serie.S01E02.mkv", [
            _make_candidate_dict("tvdb-other", "Autre Série")
        ])

        service.list_pending.return_value = [pending, other]
        selected = SearchResult(id="tvdb-999", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 0
        service.validate_candidate.assert_not_called()
