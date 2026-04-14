"""
Tests pour AnomalyDetector (phase 42-01, tache 3a).

Le detecteur refait une recherche TVDB independante depuis les filenames
parses (title + year + season) pour retrouver le bon tvdb_id, meme si
le filtrage du pipeline de matching a elimine la serie cible parce que
son canon TVDB est plus court que les episodes locaux.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.entities.video import (
    PendingValidation,
    ValidationStatus,
    VideoFile,
)
from src.core.ports.api_clients import SearchResult
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.anomaly_detector import AnomalyDetector


TVDB_ID = 246063
SEASON_4 = 4


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_pending(filename: str) -> PendingValidation:
    """Construit un PendingValidation minimal (candidats vides : le
    detecteur refait la recherche TVDB lui-meme)."""
    vf = VideoFile(path=f"/downloads/{filename}", filename=filename)
    return PendingValidation(
        id=filename,
        video_file=vf,
        candidates=[],
        validation_status=ValidationStatus.PENDING,
    )


def _tvdb_search_result(tvdb_id: int, title: str, year: int = 2010):
    return SearchResult(
        id=str(tvdb_id),
        title=title,
        year=year,
        score=0.0,
        source="tvdb",
    )


@pytest.fixture
def pending_repo():
    repo = MagicMock()
    repo.list_pending = MagicMock(return_value=[])
    return repo


@pytest.fixture
def tvdb_client():
    client = SimpleNamespace()
    client.search = AsyncMock(return_value=[])
    client.get_season_episode_count = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_detects_excess_group(session, pending_repo, tvdb_client):
    """4 pendings S04E05-08 + TVDB search renvoie The Big C + count=4 → 1 groupe."""
    pending_repo.list_pending.return_value = [
        _make_pending(f"The.Big.C.S04E0{n}.mkv") for n in (5, 6, 7, 8)
    ]
    tvdb_client.search = AsyncMock(
        return_value=[_tvdb_search_result(TVDB_ID, "The Big C", 2010)]
    )
    tvdb_client.get_season_episode_count = AsyncMock(return_value=4)

    detector = AnomalyDetector(session, tvdb_client, pending_repo)
    groups = await detector.find_excess_episode_groups()

    assert len(groups) == 1
    g = groups[0]
    assert g.tvdb_id == TVDB_ID
    assert g.season_number == SEASON_4
    assert g.tvdb_count == 4
    assert len(g.pendings) == 4
    assert g.episode_numbers == [5, 6, 7, 8]
    assert g.max_episode_number == 8
    assert g.series_title == "The Big C"
    assert g.series_year == 2010


@pytest.mark.asyncio
async def test_ignores_canonical(session, pending_repo, tvdb_client):
    """Episode dans le canon TVDB → aucun groupe."""
    pending_repo.list_pending.return_value = [
        _make_pending("Classic.Show.S01E02.mkv")
    ]
    tvdb_client.search = AsyncMock(
        return_value=[_tvdb_search_result(12345, "Classic Show", 2020)]
    )
    tvdb_client.get_season_episode_count = AsyncMock(return_value=10)

    detector = AnomalyDetector(session, tvdb_client, pending_repo)
    groups = await detector.find_excess_episode_groups()

    assert groups == []


@pytest.mark.asyncio
async def test_counts_validated_seasons(session, pending_repo, tvdb_client):
    """3 EpisodeModel sur saisons distinctes → validated_seasons_count=3."""
    series = SeriesModel(title="The Big C", tvdb_id=TVDB_ID, year=2010)
    session.add(series)
    session.commit()
    assert series.id is not None
    for season in (1, 2, 3):
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=season,
                episode_number=1,
                title=f"S{season}E1",
            )
        )
    session.commit()

    pending_repo.list_pending.return_value = [
        _make_pending("The.Big.C.S04E05.mkv")
    ]
    tvdb_client.search = AsyncMock(
        return_value=[_tvdb_search_result(TVDB_ID, "The Big C", 2010)]
    )
    tvdb_client.get_season_episode_count = AsyncMock(return_value=4)

    detector = AnomalyDetector(session, tvdb_client, pending_repo)
    groups = await detector.find_excess_episode_groups()

    assert len(groups) == 1
    assert groups[0].validated_seasons_count == 3


@pytest.mark.asyncio
async def test_mixed_group(session, pending_repo, tvdb_client):
    """E03 (ok), E05, E06 (excess) → 1 groupe avec seulement E05, E06."""
    pending_repo.list_pending.return_value = [
        _make_pending("The.Big.C.S04E03.mkv"),
        _make_pending("The.Big.C.S04E05.mkv"),
        _make_pending("The.Big.C.S04E06.mkv"),
    ]
    tvdb_client.search = AsyncMock(
        return_value=[_tvdb_search_result(TVDB_ID, "The Big C", 2010)]
    )
    tvdb_client.get_season_episode_count = AsyncMock(return_value=4)

    detector = AnomalyDetector(session, tvdb_client, pending_repo)
    groups = await detector.find_excess_episode_groups()

    assert len(groups) == 1
    g = groups[0]
    assert g.episode_numbers == [5, 6]
    assert len(g.pendings) == 2
    assert g.max_episode_number == 6


@pytest.mark.asyncio
async def test_ignores_low_similarity_match(session, pending_repo, tvdb_client):
    """Si TVDB ne renvoie que des titres tres differents, pas de detection."""
    pending_repo.list_pending.return_value = [
        _make_pending(f"The.Big.C.S04E0{n}.mkv") for n in (5, 6, 7, 8)
    ]
    # Resultats TVDB sans correspondance forte avec "the big c"
    tvdb_client.search = AsyncMock(
        return_value=[
            _tvdb_search_result(11111, "Documentary Special"),
            _tvdb_search_result(22222, "Random Series"),
        ]
    )
    tvdb_client.get_season_episode_count = AsyncMock(return_value=4)

    detector = AnomalyDetector(session, tvdb_client, pending_repo)
    groups = await detector.find_excess_episode_groups()

    assert groups == []
