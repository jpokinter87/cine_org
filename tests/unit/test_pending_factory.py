"""
Tests pour la prise en compte de SeasonOverrideModel dans les filtres
d'episodes (phase 42-01, tache 2).

Verifie que filter_by_episode_count consulte un override quand
``session`` est fourni, en prenant ``max(count_tvdb, override)`` comme
compteur effectif, et qu'il reste strictement retro-compatible quand
``session`` est None.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.ports.api_clients import SearchResult
from src.infrastructure.persistence.models import SeasonOverrideModel
from src.services.workflow.pending_factory import filter_by_episode_count


TVDB_ID = "246063"  # The Big C
SEASON = 4
TVDB_CANONICAL_COUNT = 4


@pytest.fixture
def engine():
    """Engine SQLite in-memory avec le schema courant."""
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def tvdb_client():
    """Mock renvoyant un count TVDB canonique fixe."""
    client = AsyncMock()
    client.get_season_episode_count = AsyncMock(return_value=TVDB_CANONICAL_COUNT)
    return client


@pytest.fixture
def candidate():
    """Candidat TVDB unique pointant sur la serie override-able."""
    return SearchResult(
        id=TVDB_ID,
        title="The Big C",
        year=2010,
        score=95.0,
        source="tvdb",
    )


@pytest.mark.asyncio
async def test_no_override_rejects_extra(tvdb_client, candidate, session):
    """Sans override, un episode au-dela du canon TVDB est filtre."""
    result = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=5, session=session
    )
    assert result == []


@pytest.mark.asyncio
async def test_override_accepts_extra(tvdb_client, candidate, session):
    """Avec override(tvdb_id, season, 8), un episode=7 est conserve."""
    session.add(
        SeasonOverrideModel(
            tvdb_id=int(TVDB_ID), season_number=SEASON, episode_count=8
        )
    )
    session.commit()

    result = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=7, session=session
    )

    assert len(result) == 1
    assert result[0].id == TVDB_ID


@pytest.mark.asyncio
async def test_override_below_tvdb(tvdb_client, candidate, session):
    """Un override inferieur au canon ne degrade pas le canon : max()."""
    session.add(
        SeasonOverrideModel(
            tvdb_id=int(TVDB_ID), season_number=SEASON, episode_count=2
        )
    )
    session.commit()

    # max(count_tvdb=4, override=2) = 4, donc episode=3 reste conserve
    result = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=3, session=session
    )
    assert len(result) == 1
    assert result[0].id == TVDB_ID

    # Et episode=5 reste filtre (canon inchange)
    result_extra = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=5, session=session
    )
    assert result_extra == []


@pytest.mark.asyncio
async def test_session_none_fallback(tvdb_client, candidate):
    """session=None : comportement strictement identique a l'existant."""
    # Canon respecte : conserve
    result_ok = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=4, session=None
    )
    assert len(result_ok) == 1

    # Au-dela du canon : filtre (aucune consultation d'override possible)
    result_extra = await filter_by_episode_count(
        tvdb_client, [candidate], season=SEASON, episode=7, session=None
    )
    assert result_extra == []
