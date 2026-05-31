"""
Tests pour SeriesEnricherService.

Verifie l'enrichissement TMDB des series TV, en particulier la lecture
des notes IMDb depuis le cache local apres recuperation de l'imdb_id.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Series
from src.core.ports.api_clients import MediaDetails
from src.services.series_enricher import (
    EnrichmentResult,
    SeriesEnricherService,
    pick_best_tv_match,
)


@pytest.fixture
def mock_series_repo():
    """Mock du repository series (save renvoie l'entite passee)."""
    repo = MagicMock()
    repo.save.side_effect = lambda s: s
    return repo


@pytest.fixture
def mock_tmdb_client():
    """Mock TMDB avec methodes async usuelles.

    Par defaut, aucune resolution par identifiant externe : ces tests couvrent
    le repli par recherche titre (et ses garde-fous annee/episodes). Les tests
    dedies a la resolution par tvdb_id/imdb_id vivent dans
    test_series_enricher_external_id.py.
    """
    client = AsyncMock()
    client.find_by_external_id = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_imdb_importer():
    """Mock du IMDbDatasetImporter (cache local).

    Par defaut, le repli par titre ne trouve rien (find_tconst_by_title -> None) :
    ces tests couvrent le chemin imdb_id-via-TMDB. Le repli par titre est teste
    a part dans test_series_enricher_imdb_title_fallback.py.
    """
    importer = MagicMock()
    importer.get_rating.return_value = None
    importer.find_tconst_by_title.return_value = None
    return importer


@pytest.fixture
def mock_episode_repo():
    """Mock du repository episodes (vide par defaut)."""
    repo = MagicMock()
    repo.get_by_series.return_value = []
    return repo


def _tmdb_search_result(id_: str, title: str, year: int):
    """Construit un SearchResult minimal compatible avec _pick_best_match."""
    obj = MagicMock()
    obj.id = id_
    obj.title = title
    obj.original_title = None
    obj.year = year
    return obj


class TestSeriesEnricherWithIMDbCache:
    """Verifie la passe IMDb (cache local) apres recuperation de l'imdb_id."""

    @pytest.mark.asyncio
    async def test_imdb_rating_populated_when_importer_returns_rating(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Quand imdb_id est trouve et que le cache IMDb a une note, on la persiste."""
        # Setup serie
        series = Series(id="42", title="Forever", year=1996, tvdb_id=12345)

        # TMDB search → 1 resultat exact
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("99", "Forever", 1996)
        ]
        # TMDB details
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="99",
            title="Forever",
            year=1996,
            vote_average=7.8,
            vote_count=1500,
            is_tv=True,
        )
        # External IDs : imdb_id present
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0123456"}
        # IMDb cache local : note disponible
        mock_imdb_importer.get_rating.return_value = (8.2, 9876)

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )

        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        # Le repo a recu une serie avec imdb_rating + imdb_votes peuples
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_id == "tt0123456"
        assert saved.imdb_rating == 8.2
        assert saved.imdb_votes == 9876
        assert saved.vote_average == 7.8
        assert saved.vote_count == 1500
        mock_imdb_importer.get_rating.assert_called_once_with("tt0123456")

    @pytest.mark.asyncio
    async def test_no_imdb_importer_keeps_existing_behavior(
        self, mock_series_repo, mock_tmdb_client
    ):
        """Sans importer fourni, le service ne lit pas de cache IMDb (compat)."""
        series = Series(id="1", title="Lost", year=2004, tvdb_id=10)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("88", "Lost", 2004)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="88", title="Lost", year=2004, vote_average=8.4, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0411008"}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            # imdb_importer omis volontairement
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        # imdb_id est toujours peuple, mais note IMDb reste None
        assert saved.imdb_id == "tt0411008"
        assert saved.imdb_rating is None
        assert saved.imdb_votes is None

    @pytest.mark.asyncio
    async def test_imdb_cache_miss_leaves_ratings_none(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Si get_rating renvoie None, on n'ecrase pas avec des None erratiques."""
        series = Series(id="3", title="Forever", year=1996, tvdb_id=12345)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("99", "Forever", 1996)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="99", title="Forever", year=1996, vote_average=7.8, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0000001"}
        mock_imdb_importer.get_rating.return_value = None

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_id == "tt0000001"
        assert saved.imdb_rating is None
        assert saved.imdb_votes is None

    @pytest.mark.asyncio
    async def test_imdb_rating_skipped_when_no_imdb_id(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Pas d'imdb_id externe → on n'appelle pas le cache IMDb."""
        series = Series(id="9", title="Mystery", year=2018, tvdb_id=77)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("77", "Mystery", 2018)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="77", title="Mystery", year=2018, vote_average=6.5, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": None}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        mock_imdb_importer.get_rating.assert_not_called()

    @pytest.mark.asyncio
    async def test_year_provided_but_no_year_match_returns_none(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Garde-fou : year fourni mais aucun resultat annee-aligne -> NOT_FOUND.

        Reproduit l'ancien bug : 'Flashback' year=2011 sur TMDB ne contient
        aucun Flashback 2011, donc enrich-series ne doit pas associer le
        resultat #1 (Flashback 2025) a la place — sinon imdb_id/tmdb_id
        sont ecrases avec une serie differente.
        """
        series = Series(id="1", title="Flashback", year=2011, tvdb_id=244011)
        # TMDB ne renvoie que des Flashback non-2011
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("237979", "Flashback", 2025),
            _tmdb_search_result("88", "Flashback", 2014),
        ]

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.not_found == 1
        assert stats.enriched == 0
        # Aucun ecrasement : la serie n'a pas ete sauvee
        mock_series_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_episode_count_guard_drops_inconsistent_candidate(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer, mock_episode_repo
    ):
        """Garde-fou : si un candidat TMDB n'a pas assez d'episodes pour les
        saisons deja en base, il est rejete. Reproduit le scenario Shameless :
        DB a 12 ep en S01, candidat UK n'en propose que 7 -> rejete."""
        from src.core.entities.media import Episode

        series = Series(id="42", title="Shameless", year=2011, tvdb_id=None)

        # Episodes DB : S01 a 12 episodes (numerotation 1..12)
        mock_episode_repo.get_by_series.return_value = [
            Episode(season_number=1, episode_number=i, title=f"Ep {i}")
            for i in range(1, 13)
        ]

        # 2 candidats avec le meme titre+annee : UK (incompatible) et US (compatible)
        uk = _tmdb_search_result("1906", "Shameless", 2004)
        us = _tmdb_search_result("34307", "Shameless", 2011)
        mock_tmdb_client.search_tv.return_value = [uk, us]

        # Comptes TMDB par saison : UK S01=7, US S01=12
        async def counts_side_effect(tv_id):
            if tv_id == "1906":
                return {1: 7}  # UK
            if tv_id == "34307":
                return {1: 12}  # US
            return {}

        mock_tmdb_client.get_tv_seasons_episode_counts.side_effect = counts_side_effect

        # Details et external_ids pour le candidat retenu
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="34307", title="Shameless", year=2011, vote_average=8.2, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt1586680"}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
            episode_repo=mock_episode_repo,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        # On a bien retenu Shameless US, pas UK
        assert saved.tmdb_id == 34307
        assert saved.imdb_id == "tt1586680"

    @pytest.mark.asyncio
    async def test_episode_count_guard_no_db_episodes_keeps_all(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer, mock_episode_repo
    ):
        """Sans episodes en DB, le filtre n'est pas applique (pas de signal)."""
        series = Series(id="1", title="Forever", year=1996, tvdb_id=12345)
        mock_episode_repo.get_by_series.return_value = []  # vide

        # Si plusieurs candidats : pick_best_tv_match decide selon ses regles
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("99", "Forever", 1996)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="99", title="Forever", year=1996, vote_average=7.0, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0001"}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
            episode_repo=mock_episode_repo,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)
        assert stats.enriched == 1
        # Pas d'appel au filtre TMDB seasons (un seul candidat de toute facon)
        mock_tmdb_client.get_tv_seasons_episode_counts.assert_not_called()

    @pytest.mark.asyncio
    async def test_episode_count_guard_returns_not_found_when_none_compatible(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer, mock_episode_repo
    ):
        """Si aucun candidat ne couvre les episodes DB, on renvoie NOT_FOUND."""
        from src.core.entities.media import Episode

        series = Series(id="42", title="Mystere", year=2020, tvdb_id=None)
        mock_episode_repo.get_by_series.return_value = [
            Episode(season_number=1, episode_number=20, title="Ep 20")
        ]

        a = _tmdb_search_result("1", "Mystere", 2020)
        b = _tmdb_search_result("2", "Mystere", 2020)
        mock_tmdb_client.search_tv.return_value = [a, b]

        async def counts(tv_id):
            return {1: 5}  # tous les deux ont juste 5 ep en S01, insuffisant

        mock_tmdb_client.get_tv_seasons_episode_counts.side_effect = counts

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
            episode_repo=mock_episode_repo,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)
        assert stats.not_found == 1
        assert stats.enriched == 0
        mock_series_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_imdb_id_still_triggers_cache_lookup(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Si la serie a deja un imdb_id mais pas de note IMDb, on lit le cache."""
        series = Series(
            id="11",
            title="Suits",
            year=2011,
            tvdb_id=42,
            imdb_id="tt1632701",
            imdb_rating=None,
        )
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("100", "Suits", 2011)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="100", title="Suits", year=2011, vote_average=8.5, is_tv=True
        )
        # get_tv_external_ids ne sera pas force a etre appele car imdb_id existe deja,
        # mais on tolere les deux cas
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt1632701"}
        mock_imdb_importer.get_rating.return_value = (8.4, 50000)

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_rating == 8.4
        assert saved.imdb_votes == 50000
        mock_imdb_importer.get_rating.assert_called_once_with("tt1632701")
