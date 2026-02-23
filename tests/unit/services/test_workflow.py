"""
Tests unitaires pour WorkflowService.

Vérifie :
- _auto_validate_series_episodes : auto-validation par candidat TVDB
- _filter_by_episode_count : filtrage des candidats par nombre d'épisodes
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult
from src.services.workflow import WorkflowService, WorkflowState


def _make_pending(
    id: str,
    filename: str,
    candidates: list[dict],
    folder: str = "/downloads/series",
) -> PendingValidation:
    """Crée un PendingValidation de test."""
    return PendingValidation(
        id=id,
        video_file=VideoFile(
            path=Path(folder) / filename,
        ),
        candidates=candidates,
        validation_status=ValidationStatus.PENDING,
    )


def _make_candidate_dict(id: str, title: str, score: float = 67.0) -> dict:
    """Crée un dict candidat tel que stocké dans PendingValidation.candidates."""
    return {
        "id": id,
        "title": title,
        "score": score,
        "source": "tvdb",
    }


class TestAutoValidateSeriesEpisodes:
    """Tests pour _auto_validate_series_episodes."""

    @pytest.fixture
    def workflow(self) -> WorkflowService:
        """WorkflowService avec mocks."""
        container = MagicMock()
        service = WorkflowService(container)
        service._validation_service = MagicMock()
        service._validation_service.validate_candidate = AsyncMock()
        service._console = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_auto_validates_only_same_series(self, workflow: WorkflowService):
        """Seuls les fichiers ayant le même candidat TVDB sont auto-validés."""
        shield_candidate = _make_candidate_dict("tvdb-shield", "Marvel's Agents of S.H.I.E.L.D.")
        hpi_candidate = _make_candidate_dict("tvdb-hpi", "HPI")

        pend_shield_e22 = _make_pending("1", "shield.s03e22.mkv", [shield_candidate])
        pend_shield_e21 = _make_pending("2", "shield.s03e21.mkv", [shield_candidate])
        pend_hpi_e01 = _make_pending("3", "hpi.s01e01.mkv", [hpi_candidate])

        remaining = [pend_shield_e22, pend_shield_e21, pend_hpi_e01]
        processed_ids: set[str] = set()
        state = WorkflowState()

        candidate = SearchResult(id="tvdb-shield", title="Marvel's Agents of S.H.I.E.L.D.", source="tvdb")

        await workflow._auto_validate_series_episodes(
            pend_shield_e22, candidate, remaining, processed_ids, state
        )

        # Seul shield e21 doit être auto-validé, pas HPI
        assert "2" in processed_ids
        assert "3" not in processed_ids
        assert state.manual_validated_count == 1
        workflow._validation_service.validate_candidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auto_validate_when_no_matching_candidate(self, workflow: WorkflowService):
        """Aucun fichier auto-validé si aucun n'a le candidat dans ses candidats."""
        pend_main = _make_pending("1", "shield.s03e22.mkv", [
            _make_candidate_dict("tvdb-shield", "Shield")
        ])
        pend_other = _make_pending("2", "alexandre.e01.avi", [
            _make_candidate_dict("tvdb-alex", "Alexandre Le Grand")
        ])

        remaining = [pend_main, pend_other]
        processed_ids: set[str] = set()
        state = WorkflowState()

        candidate = SearchResult(id="tvdb-shield", title="Shield", source="tvdb")

        await workflow._auto_validate_series_episodes(
            pend_main, candidate, remaining, processed_ids, state
        )

        assert len(processed_ids) == 0
        assert state.manual_validated_count == 0
        workflow._validation_service.validate_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_matching_candidate_from_other_list(self, workflow: WorkflowService):
        """Utilise le candidat correspondant de la liste de l'autre fichier (pas l'original)."""
        pend_main = _make_pending("1", "shield.s03e22.mkv", [
            _make_candidate_dict("tvdb-shield", "Shield", score=67.0)
        ])
        # L'autre fichier a le même candidat mais avec un score différent
        pend_other = _make_pending("2", "shield.s03e21.mkv", [
            _make_candidate_dict("tvdb-shield", "Shield", score=70.0),
            _make_candidate_dict("tvdb-other", "Other Show", score=30.0),
        ])

        remaining = [pend_main, pend_other]
        processed_ids: set[str] = set()
        state = WorkflowState()

        candidate = SearchResult(id="tvdb-shield", title="Shield", source="tvdb")

        await workflow._auto_validate_series_episodes(
            pend_main, candidate, remaining, processed_ids, state
        )

        # Vérifie qu'on utilise le candidat de la liste de l'autre fichier
        call_args = workflow._validation_service.validate_candidate.call_args
        validated_candidate = call_args[0][1]
        assert validated_candidate.id == "tvdb-shield"
        assert validated_candidate.score == 70.0

    @pytest.mark.asyncio
    async def test_skips_already_processed(self, workflow: WorkflowService):
        """Les fichiers déjà traités sont ignorés."""
        candidate_dict = _make_candidate_dict("tvdb-shield", "Shield")
        pend_main = _make_pending("1", "shield.s03e22.mkv", [candidate_dict])
        pend_already = _make_pending("2", "shield.s03e21.mkv", [candidate_dict])

        remaining = [pend_main, pend_already]
        processed_ids: set[str] = {"2"}  # Déjà traité
        state = WorkflowState()

        candidate = SearchResult(id="tvdb-shield", title="Shield", source="tvdb")

        await workflow._auto_validate_series_episodes(
            pend_main, candidate, remaining, processed_ids, state
        )

        assert state.manual_validated_count == 0
        workflow._validation_service.validate_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_same_folder_different_series_not_validated(self, workflow: WorkflowService):
        """Des fichiers dans le même dossier mais de séries différentes ne sont PAS auto-validés."""
        same_folder = "/downloads/series"

        pend_shield = _make_pending("1", "shield.s03e22.mkv", [
            _make_candidate_dict("tvdb-shield", "Shield")
        ], folder=same_folder)
        pend_hpi = _make_pending("2", "hpi.s01e01.mkv", [
            _make_candidate_dict("tvdb-hpi", "HPI")
        ], folder=same_folder)
        pend_andor = _make_pending("3", "andor.s02e01.mkv", [
            _make_candidate_dict("tvdb-andor", "Andor")
        ], folder=same_folder)

        remaining = [pend_shield, pend_hpi, pend_andor]
        processed_ids: set[str] = set()
        state = WorkflowState()

        candidate = SearchResult(id="tvdb-shield", title="Shield", source="tvdb")

        await workflow._auto_validate_series_episodes(
            pend_shield, candidate, remaining, processed_ids, state
        )

        # Aucun autre fichier ne doit être auto-validé
        assert len(processed_ids) == 0
        assert state.manual_validated_count == 0


class TestFilterByEpisodeCount:
    """Tests pour _filter_by_episode_count."""

    @pytest.fixture
    def workflow(self) -> WorkflowService:
        """WorkflowService avec tvdb_client mocké."""
        container = MagicMock()
        service = WorkflowService(container)
        service._tvdb_client = MagicMock()
        service._tvdb_client.get_season_episode_count = AsyncMock()
        service._console = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_eliminates_candidate_when_episode_exceeds_count(
        self, workflow: WorkflowService
    ):
        """Un candidat avec episode > count est elimine."""
        # Fichier S03E22 mais la serie n'a que 10 episodes en S03
        workflow._tvdb_client.get_season_episode_count.return_value = 10

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=3, episode=22)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_keeps_candidate_when_episode_within_count(
        self, workflow: WorkflowService
    ):
        """Un candidat avec episode <= count est conserve."""
        workflow._tvdb_client.get_season_episode_count.return_value = 22

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=3, episode=22)

        assert len(result) == 1
        assert result[0].id == "111"

    @pytest.mark.asyncio
    async def test_keeps_candidate_when_season_not_found(
        self, workflow: WorkflowService
    ):
        """Un candidat dont la saison n'existe pas (None) est conserve par precaution."""
        workflow._tvdb_client.get_season_episode_count.return_value = None

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=99, episode=1)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filters_mixed_candidates(self, workflow: WorkflowService):
        """Parmi plusieurs candidats, ceux incompatibles (episode > count) sont elimines."""
        async def mock_count(series_id, season):
            if series_id == "111":
                return 22  # compatible (episode 22 <= 22)
            elif series_id == "222":
                return 10  # incompatible (episode 22 > 10)
            else:
                return None  # saison inexistante → conserve par precaution

        workflow._tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
            SearchResult(id="222", title="Serie B", score=85.0, source="tvdb"),
            SearchResult(id="333", title="Serie C", score=60.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=3, episode=22)

        # Serie A (compatible) et Serie C (count=None, conservee par precaution)
        assert len(result) == 2
        assert result[0].id == "111"
        assert result[1].id == "333"

    @pytest.mark.asyncio
    async def test_returns_all_when_no_tvdb_client(self, workflow: WorkflowService):
        """Sans tvdb_client, tous les candidats sont conserves."""
        workflow._tvdb_client = None

        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=3, episode=22)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, workflow: WorkflowService):
        """En cas d'erreur API, le candidat est conserve (pas elimine)."""
        workflow._tvdb_client.get_season_episode_count = AsyncMock(
            side_effect=Exception("API error")
        )

        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(candidates, season=3, episode=22)

        # En cas d'erreur, on conserve le candidat par precaution
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_keeps_all_compatible_candidates(
        self, workflow: WorkflowService
    ):
        """Tous les candidats compatibles (episode <= count) sont conserves."""
        async def mock_count(series_id, season):
            if series_id == "star-crossed":
                return 13
            elif series_id == "crossed":
                return 28
            return None

        workflow._tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        candidates = [
            SearchResult(id="crossed", title="Crossed", score=75.0, source="tvdb"),
            SearchResult(id="star-crossed", title="Star-Crossed", score=70.0, source="tvdb"),
        ]

        result = await workflow._filter_by_episode_count(
            candidates, season=1, episode=5
        )

        assert len(result) == 2
