"""
Tests unitaires pour la cascade série dans les routes web de validation.

Vérifie :
- _auto_validate_series_episodes : cascade par candidat existant
- _auto_validate_series_episodes : fallback par titre guessit (candidats vides)
- validate_candidate (route) : déclenchement de la cascade selon la source
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult
from src.web.routes.validation import (
    _auto_validate_series_episodes,
    validate_candidate,
)


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
    async def test_cascade_fallback_malgre_candidats_non_correspondants(self, service):
        """L'épisode a des candidats, mais aucun ne correspond → fallback titre."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        other = _make_pending(
            "2",
            "Ma.Serie.S01E02.mkv",
            [_make_candidate_dict("tvdb-other", "Autre Série")],
        )

        service.list_pending.return_value = [pending, other]
        selected = SearchResult(id="tvdb-999", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 1
        service.validate_candidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_cascade_fichier_non_serie(self, service):
        """Le fallback titre ne touche pas un fichier non détecté comme série."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        film = _make_pending(
            "2",
            "Ma.Serie.2011.1080p.mkv",
            [{"id": "42", "title": "Ma Série", "score": 90.0, "source": "tmdb"}],
        )

        service.list_pending.return_value = [pending, film]
        selected = SearchResult(id="tvdb-999", title="Ma Série", source="tvdb")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 0
        service.validate_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_id_identique_source_differente_pas_de_faux_match(self, service):
        """Un ID identique dans une autre base ne doit pas être pris pour le candidat."""
        pending = _make_pending("1", "Ma.Serie.S01E01.mkv", [])
        other = _make_pending(
            "2",
            "Autre.Show.S01E02.mkv",
            [
                _make_candidate_dict("1641349", "Autre Série")  # source tvdb
            ],
        )

        service.list_pending.return_value = [pending, other]
        selected = SearchResult(id="1641349", title="Ma Série", source="tmdb_tv")

        count = await _auto_validate_series_episodes(service, pending, selected)

        assert count == 0
        service.validate_candidate.assert_not_called()


class TestCascadeDepuisRouteValidate:
    """La route /validate doit déclencher la cascade pour toutes les sources série."""

    @pytest.fixture
    def service(self):
        svc = MagicMock()
        svc.validate_candidate = AsyncMock()
        return svc

    def _request(self, service):
        request = MagicMock()
        request.app.state.container.validation_service.return_value = service
        return request

    @pytest.mark.asyncio
    async def test_cascade_apres_validation_par_id_imdb(self, service):
        """Validation par ID IMDb (source tmdb_tv) → cascade sur les épisodes."""
        pending = _make_pending("1", "TERRANOVA.S01E01.MULTI.VFF.1080P.mkv", [])
        other = _make_pending("2", "TERRANOVA.S01E02.MULTI.VFF.1080P.mkv", [])

        service.get_pending_by_id.return_value = pending
        service.list_pending.return_value = [pending, other]

        await validate_candidate(
            self._request(service),
            "1",
            candidate_id="1641349",
            source="tmdb_tv",
            title="Terra Nova",
            year="2011",
        )

        # 1 validation manuelle + 1 cascade
        assert service.validate_candidate.await_count == 2

    @pytest.mark.asyncio
    async def test_pas_de_cascade_pour_un_film(self, service):
        """Validation d'un film (source tmdb) → aucune cascade."""
        pending = _make_pending("1", "Un.Film.2011.1080p.mkv", [])
        other = _make_pending("2", "Un.Film.2011.1080p.autre.mkv", [])

        service.get_pending_by_id.return_value = pending
        service.list_pending.return_value = [pending, other]

        await validate_candidate(
            self._request(service),
            "1",
            candidate_id="12345",
            source="tmdb",
            title="Un Film",
            year="2011",
        )

        assert service.validate_candidate.await_count == 1
