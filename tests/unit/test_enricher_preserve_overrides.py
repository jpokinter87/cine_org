"""
Tests du flag preserve_overrides dans movies_enricher et series_enricher
(phase 42-02, tache 3).

Les champs poster_path / overview / director / cast doivent rester
inchanges quand preserve_overrides=True. Les autres champs (vote_average,
etc.) restent enrichis normalement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Movie, Series
from src.core.ports.api_clients import MediaDetails
from src.services.movies_enricher import (
    EnrichmentResult,
    MoviesEnricherService,
)
from src.services.series_enricher import SeriesEnricherService


# ─── MoviesEnricherService ────────────────────────────────────────────────


def _movie_details(**overrides) -> MediaDetails:
    defaults = dict(
        id="42",
        title="Test",
        original_title=None,
        year=2020,
        genres=("Drame",),
        duration_seconds=None,
        overview="New overview",
        poster_url="https://tmdb/new-poster.jpg",
        director="New Director",
        cast=("New Actor 1", "New Actor 2"),
        vote_average=7.5,
        vote_count=1000,
    )
    defaults.update(overrides)
    return MediaDetails(**defaults)


@pytest.fixture
def movie_repo():
    repo = MagicMock()
    repo.save = MagicMock(side_effect=lambda m: m)
    return repo


@pytest.fixture
def tmdb_client():
    client = MagicMock()
    client.get_details = AsyncMock(return_value=_movie_details())
    return client


@pytest.mark.asyncio
async def test_enricher_skips_protected_fields_when_preserve_true(
    movie_repo, tmdb_client
):
    movie = Movie(
        id="1",
        tmdb_id=42,
        title="Old",
        director="Old Director",
        cast=("Old Actor",),
        poster_path="https://old/poster.jpg",
        preserve_overrides=True,
    )
    service = MoviesEnricherService(
        movie_repo=movie_repo, tmdb_client=tmdb_client
    )
    stats = await service.enrich_credits([movie], rate_limit_seconds=0)

    assert stats.enriched == 1
    # Champs proteges : inchanges
    assert movie.director == "Old Director"
    assert movie.cast == ("Old Actor",)
    assert movie.poster_path == "https://old/poster.jpg"


@pytest.mark.asyncio
async def test_enricher_writes_when_preserve_false(movie_repo, tmdb_client):
    movie = Movie(
        id="1",
        tmdb_id=42,
        title="Old",
        director="Old Director",
        cast=("Old Actor",),
        poster_path=None,  # vide → l'enricher doit le remplir
        preserve_overrides=False,
    )
    service = MoviesEnricherService(
        movie_repo=movie_repo, tmdb_client=tmdb_client
    )
    stats = await service.enrich_credits([movie], rate_limit_seconds=0)

    assert stats.enriched == 1
    assert movie.director == "New Director"
    assert movie.cast == ("New Actor 1", "New Actor 2")
    assert movie.poster_path == "https://tmdb/new-poster.jpg"


@pytest.mark.asyncio
async def test_enricher_preserve_does_not_skip_enrichment_flow(
    movie_repo, tmdb_client
):
    """preserve_overrides=True : l'enrichment status reste SUCCESS
    (pas SKIPPED) — les champs non-override peuvent etre mis a jour
    par d'autres enrichers."""
    movie = Movie(
        id="1",
        tmdb_id=42,
        title="Movie",
        preserve_overrides=True,
    )
    service = MoviesEnricherService(
        movie_repo=movie_repo, tmdb_client=tmdb_client
    )
    stats = await service.enrich_credits([movie], rate_limit_seconds=0)

    assert stats.enriched == 1
    assert stats.skipped == 0
    # save est bien appele (permet aux autres fields de passer si besoin)
    movie_repo.save.assert_called_once()


# ─── SeriesEnricherService ────────────────────────────────────────────────


def _series_details(**overrides) -> MediaDetails:
    defaults = dict(
        id="99",
        title="Série",
        original_title="Series original",
        year=2020,
        genres=("Drame",),
        duration_seconds=None,
        overview="New series overview",
        poster_url="https://tmdb/new-series.jpg",
        director="New Showrunner",
        cast=("Actor A", "Actor B"),
        vote_average=8.1,
        vote_count=500,
    )
    defaults.update(overrides)
    return MediaDetails(**defaults)


@pytest.fixture
def series_repo():
    repo = MagicMock()
    repo.save = MagicMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def tmdb_tv_client():
    client = MagicMock()
    # search_tv retourne un SearchResult minimal
    search_result = MagicMock()
    search_result.id = "99"
    search_result.title = "Série"
    search_result.year = 2020
    client.search_tv = AsyncMock(return_value=[search_result])
    client.get_tv_details = AsyncMock(return_value=_series_details())
    client.get_tv_external_ids = AsyncMock(return_value={"imdb_id": "tt999"})
    return client


@pytest.mark.asyncio
async def test_series_enricher_preserves_protected_fields(
    series_repo, tmdb_tv_client
):
    series = Series(
        id="1",
        title="Série",
        year=2020,
        overview="Old overview",
        poster_path="https://old/series.jpg",
        director="Old Showrunner",
        cast=("Old Actor",),
        preserve_overrides=True,
    )
    service = SeriesEnricherService(
        series_repo=series_repo, tmdb_client=tmdb_tv_client
    )
    await service.enrich_series([series], rate_limit_seconds=0)

    # Champs proteges : inchanges
    assert series.overview == "Old overview"
    assert series.poster_path == "https://old/series.jpg"
    assert series.director == "Old Showrunner"
    assert series.cast == ("Old Actor",)
    # Champs non-proteges : enrichis
    assert series.vote_average == 8.1
    assert series.vote_count == 500
    assert series.tmdb_id == 99


@pytest.mark.asyncio
async def test_series_enricher_writes_when_preserve_false(
    series_repo, tmdb_tv_client
):
    series = Series(
        id="1",
        title="Série",
        year=2020,
        preserve_overrides=False,
    )
    service = SeriesEnricherService(
        series_repo=series_repo, tmdb_client=tmdb_tv_client
    )
    await service.enrich_series([series], rate_limit_seconds=0)

    assert series.overview == "New series overview"
    assert series.poster_path == "https://tmdb/new-series.jpg"
    assert series.director == "New Showrunner"
    assert series.cast == ("Actor A", "Actor B")
