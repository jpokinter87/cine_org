"""
Tests unitaires pour WorkflowService.

Vérifie :
- _auto_validate_series_episodes : auto-validation par candidat TVDB
- _filter_by_episode_count : filtrage des candidats par nombre d'épisodes
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import MediaDetails, SearchResult
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.services.scanner import ScanResult
from src.services.workflow import WorkflowService, WorkflowState
from src.services.workflow.pending_factory import (
    create_pending_validation,
    filter_by_episode_count,
)


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
        shield_candidate = _make_candidate_dict(
            "tvdb-shield", "Marvel's Agents of S.H.I.E.L.D."
        )
        hpi_candidate = _make_candidate_dict("tvdb-hpi", "HPI")

        pend_shield_e22 = _make_pending("1", "shield.s03e22.mkv", [shield_candidate])
        pend_shield_e21 = _make_pending("2", "shield.s03e21.mkv", [shield_candidate])
        pend_hpi_e01 = _make_pending("3", "hpi.s01e01.mkv", [hpi_candidate])

        remaining = [pend_shield_e22, pend_shield_e21, pend_hpi_e01]
        processed_ids: set[str] = set()
        state = WorkflowState()

        candidate = SearchResult(
            id="tvdb-shield", title="Marvel's Agents of S.H.I.E.L.D.", source="tvdb"
        )

        await workflow._auto_validate_series_episodes(
            pend_shield_e22, candidate, remaining, processed_ids, state
        )

        # Seul shield e21 doit être auto-validé, pas HPI
        assert "2" in processed_ids
        assert "3" not in processed_ids
        assert state.manual_validated_count == 1
        workflow._validation_service.validate_candidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auto_validate_when_no_matching_candidate(
        self, workflow: WorkflowService
    ):
        """Aucun fichier auto-validé si aucun n'a le candidat dans ses candidats."""
        pend_main = _make_pending(
            "1", "shield.s03e22.mkv", [_make_candidate_dict("tvdb-shield", "Shield")]
        )
        pend_other = _make_pending(
            "2",
            "alexandre.e01.avi",
            [_make_candidate_dict("tvdb-alex", "Alexandre Le Grand")],
        )

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
    async def test_uses_matching_candidate_from_other_list(
        self, workflow: WorkflowService
    ):
        """Utilise le candidat correspondant de la liste de l'autre fichier (pas l'original)."""
        pend_main = _make_pending(
            "1",
            "shield.s03e22.mkv",
            [_make_candidate_dict("tvdb-shield", "Shield", score=67.0)],
        )
        # L'autre fichier a le même candidat mais avec un score différent
        pend_other = _make_pending(
            "2",
            "shield.s03e21.mkv",
            [
                _make_candidate_dict("tvdb-shield", "Shield", score=70.0),
                _make_candidate_dict("tvdb-other", "Other Show", score=30.0),
            ],
        )

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
    async def test_all_same_folder_different_series_not_validated(
        self, workflow: WorkflowService
    ):
        """Des fichiers dans le même dossier mais de séries différentes ne sont PAS auto-validés."""
        same_folder = "/downloads/series"

        pend_shield = _make_pending(
            "1",
            "shield.s03e22.mkv",
            [_make_candidate_dict("tvdb-shield", "Shield")],
            folder=same_folder,
        )
        pend_hpi = _make_pending(
            "2",
            "hpi.s01e01.mkv",
            [_make_candidate_dict("tvdb-hpi", "HPI")],
            folder=same_folder,
        )
        pend_andor = _make_pending(
            "3",
            "andor.s02e01.mkv",
            [_make_candidate_dict("tvdb-andor", "Andor")],
            folder=same_folder,
        )

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
    """Tests pour filter_by_episode_count (pending_factory)."""

    @pytest.fixture
    def tvdb_client(self) -> MagicMock:
        """Client TVDB mocké."""
        client = MagicMock()
        client.get_season_episode_count = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_eliminates_candidate_when_episode_exceeds_count(self, tvdb_client):
        """Un candidat avec episode > count est elimine."""
        tvdb_client.get_season_episode_count.return_value = 10

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=3, episode=22
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_keeps_candidate_when_episode_within_count(self, tvdb_client):
        """Un candidat avec episode <= count est conserve."""
        tvdb_client.get_season_episode_count.return_value = 22

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=3, episode=22
        )

        assert len(result) == 1
        assert result[0].id == "111"

    @pytest.mark.asyncio
    async def test_keeps_candidate_when_season_not_found(self, tvdb_client):
        """Un candidat dont la saison n'existe pas (None) est conserve par precaution."""
        tvdb_client.get_season_episode_count.return_value = None

        candidates = [
            SearchResult(id="111", title="Serie A", score=67.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=99, episode=1
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filters_mixed_candidates(self, tvdb_client):
        """Parmi plusieurs candidats, ceux incompatibles (episode > count) sont elimines."""

        async def mock_count(series_id, season):
            if series_id == "111":
                return 22  # compatible (episode 22 <= 22)
            elif series_id == "222":
                return 10  # incompatible (episode 22 > 10)
            else:
                return None  # saison inexistante → conserve par precaution

        tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
            SearchResult(id="222", title="Serie B", score=85.0, source="tvdb"),
            SearchResult(id="333", title="Serie C", score=60.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=3, episode=22
        )

        # Serie A (compatible) et Serie C (count=None, conservee par precaution)
        assert len(result) == 2
        assert result[0].id == "111"
        assert result[1].id == "333"

    @pytest.mark.asyncio
    async def test_returns_all_when_no_tvdb_client(self):
        """Sans tvdb_client, tous les candidats sont conserves."""
        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(None, candidates, season=3, episode=22)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, tvdb_client):
        """En cas d'erreur API, le candidat est conserve (pas elimine)."""
        tvdb_client.get_season_episode_count = AsyncMock(
            side_effect=Exception("API error")
        )

        candidates = [
            SearchResult(id="111", title="Serie A", score=90.0, source="tvdb"),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=3, episode=22
        )

        # En cas d'erreur, on conserve le candidat par precaution
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_keeps_all_compatible_candidates(self, tvdb_client):
        """Tous les candidats compatibles (episode <= count) sont conserves."""

        async def mock_count(series_id, season):
            if series_id == "star-crossed":
                return 13
            elif series_id == "crossed":
                return 28
            return None

        tvdb_client.get_season_episode_count = AsyncMock(side_effect=mock_count)

        candidates = [
            SearchResult(id="crossed", title="Crossed", score=75.0, source="tvdb"),
            SearchResult(
                id="star-crossed", title="Star-Crossed", score=70.0, source="tvdb"
            ),
        ]

        result = await filter_by_episode_count(
            tvdb_client, candidates, season=1, episode=5
        )

        assert len(result) == 2


def _make_scan_result(
    title: str,
    season: int,
    episode: int,
    year: int | None = 2022,
) -> ScanResult:
    """Crée un ScanResult de série pour les tests."""
    return ScanResult(
        video_file=VideoFile(
            path=Path(f"/downloads/{title}.S{season:02d}E{episode:02d}.mkv"),
        ),
        parsed_info=ParsedFilename(
            title=title,
            year=year,
            season=season,
            episode=episode,
            media_type=MediaType.SERIES,
        ),
        detected_type=MediaType.SERIES,
        source_directory="Series",
        corrected_location=False,
    )


class TestSeriesCache:
    """Tests pour le cache mémoire série dans create_pending_validation."""

    @pytest.fixture
    def tmdb_client(self) -> MagicMock:
        """Client TMDB mocké : ne porte plus la recherche série (passée sur TVDB)."""
        client = MagicMock()
        client._api_key = "fake-key"
        return client

    @pytest.fixture
    def tvdb_client(self) -> MagicMock:
        """Client TVDB mocké : recherche + détails (filtre doc) + comptage."""
        client = MagicMock()
        client._api_key = "fake-key"
        client.search = AsyncMock(
            return_value=[
                SearchResult(id="374506", title="From", year=2022, source="tvdb"),
            ]
        )
        client.get_details = AsyncMock(
            return_value=MediaDetails(id="374506", title="From", genres=("Drama",))
        )
        client.get_season_episode_count = AsyncMock(return_value=10)
        return client

    @pytest.fixture
    def matcher(self) -> MagicMock:
        """Matcher mocké qui retourne les résultats tels quels avec score."""
        m = MagicMock()
        m.score_results.return_value = [
            SearchResult(
                id="374506", title="From", year=2022, score=100.0, source="tvdb"
            ),
        ]
        return m

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_search_same_season(
        self, tmdb_client, tvdb_client, matcher
    ):
        """Plusieurs épisodes de la même saison ne déclenchent qu'une seule recherche API."""
        series_cache: dict[tuple[str, int | None], list] = {}

        for ep in range(1, 6):
            scan = _make_scan_result("From", season=1, episode=ep)
            await create_pending_validation(
                scan,
                matcher,
                tmdb_client,
                tvdb_client,
                series_cache=series_cache,
            )

        # search() et score_results() appelés une seule fois
        tvdb_client.search.assert_called_once_with("From", year=2022)
        matcher.score_results.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_search_across_seasons(
        self, tmdb_client, tvdb_client, matcher
    ):
        """Épisodes de saisons différentes partagent le même cache de recherche."""
        series_cache: dict[tuple[str, int | None], list] = {}

        episodes = [
            ("From", 1, 1),
            ("From", 1, 5),
            ("From", 2, 1),
            ("From", 2, 8),
            ("From", 3, 1),
        ]
        for title, season, ep in episodes:
            scan = _make_scan_result(title, season=season, episode=ep)
            await create_pending_validation(
                scan,
                matcher,
                tmdb_client,
                tvdb_client,
                series_cache=series_cache,
            )

        # Recherche unique malgré 3 saisons différentes
        tvdb_client.search.assert_called_once()
        matcher.score_results.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_by_episode_count_still_called_per_episode(
        self, tmdb_client, tvdb_client, matcher
    ):
        """Le filtrage par episode count est toujours fait par épisode (dépend de la saison)."""
        series_cache: dict[tuple[str, int | None], list] = {}

        for ep in range(1, 4):
            scan = _make_scan_result("From", season=1, episode=ep)
            await create_pending_validation(
                scan,
                matcher,
                tmdb_client,
                tvdb_client,
                series_cache=series_cache,
            )

        # get_season_episode_count appelé pour chaque épisode (vérification par saison)
        assert tvdb_client.get_season_episode_count.call_count == 3

    @pytest.mark.asyncio
    async def test_different_series_not_mixed_in_cache(
        self, tmdb_client, tvdb_client, matcher
    ):
        """Deux séries différentes ont des entrées de cache distinctes."""

        # Configurer des réponses différentes par titre
        async def mock_search(title, year=None):
            if "From" in title:
                return [
                    SearchResult(id="374506", title="From", year=2022, source="tvdb")
                ]
            return [SearchResult(id="999", title="Lost", year=2004, source="tvdb")]

        tvdb_client.search = AsyncMock(side_effect=mock_search)

        def mock_score(results, title, year, duration, is_series=False):
            return [
                SearchResult(
                    id=results[0].id,
                    title=results[0].title,
                    year=results[0].year,
                    score=100.0,
                    source="tvdb",
                )
            ]

        matcher.score_results.side_effect = mock_score

        series_cache: dict[tuple[str, int | None], list] = {}

        scan_from = _make_scan_result("From", season=1, episode=1, year=2022)
        scan_lost = _make_scan_result("Lost", season=1, episode=1, year=2004)
        scan_from2 = _make_scan_result("From", season=2, episode=1, year=2022)

        vf1, p1 = await create_pending_validation(
            scan_from,
            matcher,
            tmdb_client,
            tvdb_client,
            series_cache=series_cache,
        )
        vf2, p2 = await create_pending_validation(
            scan_lost,
            matcher,
            tmdb_client,
            tvdb_client,
            series_cache=series_cache,
        )
        vf3, p3 = await create_pending_validation(
            scan_from2,
            matcher,
            tmdb_client,
            tvdb_client,
            series_cache=series_cache,
        )

        # 2 recherches : From + Lost (pas 3)
        assert tvdb_client.search.call_count == 2
        # From et Lost ont des candidats différents
        assert p1.candidates[0]["id"] == "374506"
        assert p2.candidates[0]["id"] == "999"
        assert p3.candidates[0]["id"] == "374506"

    @pytest.mark.asyncio
    async def test_without_cache_search_repeated(
        self, tmdb_client, tvdb_client, matcher
    ):
        """Sans series_cache, chaque épisode déclenche une recherche."""
        for ep in range(1, 4):
            scan = _make_scan_result("From", season=1, episode=ep)
            await create_pending_validation(
                scan,
                matcher,
                tmdb_client,
                tvdb_client,
            )

        # 3 appels search sans cache
        assert tvdb_client.search.call_count == 3
        assert matcher.score_results.call_count == 3


class TestAutoValidateSkipsAmbiguous:
    """L'étape d'auto-validation doit épargner les lots homonymes."""

    @pytest.fixture
    def workflow(self) -> WorkflowService:
        import io

        from rich.console import Console

        service = WorkflowService(MagicMock())
        # Console réelle (silencieuse) : rich.Progress a besoin d'une horloge
        service._console = Console(file=io.StringIO())
        service._validation_service = MagicMock()
        service._validation_service.process_auto_validation = AsyncMock(
            return_value=MagicMock(auto_validated=True)
        )
        service._validation_service.collect_season_remap_ids = AsyncMock(
            return_value={}
        )
        return service

    @pytest.mark.asyncio
    async def test_lot_homonyme_non_auto_valide(self, workflow: WorkflowService):
        """Les fichiers signalés ambigus partent en validation manuelle."""
        pendings = [
            _make_pending("1", "The.Killing.S01E01.mkv", []),
            _make_pending("2", "The.Killing.S01E14.mkv", []),
        ]
        workflow._validation_service.list_pending.return_value = pendings
        workflow._validation_service.collect_ambiguous_ids.return_value = {"1", "2"}

        state = WorkflowState()
        await workflow._auto_validate(state)

        workflow._validation_service.process_auto_validation.assert_not_called()
        assert state.auto_validated_count == 0

    @pytest.mark.asyncio
    async def test_lot_coherent_auto_valide_normalement(
        self, workflow: WorkflowService
    ):
        """Sans ambiguïté, l'auto-validation garde son comportement."""
        pendings = [
            _make_pending("1", "Fargo.S01E01.mkv", []),
            _make_pending("2", "Fargo.S01E02.mkv", []),
        ]
        workflow._validation_service.list_pending.return_value = pendings
        workflow._validation_service.collect_ambiguous_ids.return_value = set()

        state = WorkflowState()
        await workflow._auto_validate(state)

        assert workflow._validation_service.process_auto_validation.await_count == 2
        assert state.auto_validated_count == 2

    @pytest.mark.asyncio
    async def test_numerotation_decalee_part_en_validation_manuelle(
        self, workflow: WorkflowService
    ):
        """Un arc livré en cours n'est jamais auto-validé : l'humain arbitre."""
        from src.services.season_remap import SeasonRemap

        pendings = [
            _make_pending("1", "BLEACH.Thousand-Year.Blood.War.S02E05.mkv", []),
            _make_pending("2", "Fargo.S01E01.mkv", []),
        ]
        workflow._validation_service.list_pending.return_value = pendings
        workflow._validation_service.collect_ambiguous_ids.return_value = set()
        workflow._validation_service.collect_season_remap_ids = AsyncMock(
            return_value={
                "1": SeasonRemap(
                    source_season=2,
                    source_episode=5,
                    target_season=17,
                    target_episode=18,
                    season_name="Bleach: Thousand-Year Blood War",
                    cour=2,
                )
            }
        )

        state = WorkflowState()
        await workflow._auto_validate(state)

        assert workflow._validation_service.process_auto_validation.await_count == 1
        assert state.auto_validated_count == 1
