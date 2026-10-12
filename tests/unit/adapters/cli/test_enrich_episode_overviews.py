"""enrich-episode-titles --overviews : rattrapage des résumés d'épisodes.

Sans l'option, seuls les épisodes sans titre sont traités (comportement
historique). Avec l'option, les épisodes sans résumé le reçoivent aussi ; un
titre déjà présent n'est jamais écrasé.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.cli.commands.import_commands import _enrich_episode_titles_async
from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel

enrich = _enrich_episode_titles_async.__wrapped__


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        series = SeriesModel(title="Mouche", year=2019, tvdb_id=364009)
        s.add(series)
        s.commit()
        s.refresh(series)
        for number, title, overview in (
            (1, "", None),
            (2, "Épisode 2", None),
            (3, "Titre maison", "Résumé existant"),
        ):
            s.add(
                EpisodeModel(
                    series_id=series.id,
                    season_number=1,
                    episode_number=number,
                    title=title,
                    overview=overview,
                )
            )
        s.commit()
        yield s


def _container(session):
    tvdb = MagicMock()
    tvdb.get_episode_details = AsyncMock(
        side_effect=lambda sid, season, number: EpisodeDetails(
            id=str(number),
            title=f"TVDB {number}",
            season_number=season,
            episode_number=number,
            overview=f"Résumé TVDB {number}",
        )
    )
    tvdb.close = AsyncMock()
    container = MagicMock()
    container.episode_repository.return_value._session = session
    container.tvdb_client.return_value = tvdb
    return container


def _episodes(session):
    session.expire_all()
    rows = session.query(EpisodeModel).order_by(EpisodeModel.episode_number).all()
    return [(e.title, e.overview) for e in rows]


@pytest.mark.asyncio
async def test_default_only_fills_missing_titles(session):
    await enrich(_container(session), False, 0)

    assert _episodes(session) == [
        ("TVDB 1", "Résumé TVDB 1"),
        ("Épisode 2", None),
        ("Titre maison", "Résumé existant"),
    ]


@pytest.mark.asyncio
async def test_overviews_fills_missing_overviews_without_touching_titles(session):
    await enrich(_container(session), False, 0, overviews=True)

    assert _episodes(session) == [
        ("TVDB 1", "Résumé TVDB 1"),
        ("Épisode 2", "Résumé TVDB 2"),
        ("Titre maison", "Résumé existant"),
    ]


@pytest.mark.asyncio
async def test_overviews_dry_run_writes_nothing(session):
    await enrich(_container(session), True, 0, overviews=True)

    assert _episodes(session) == [
        ("", None),
        ("Épisode 2", None),
        ("Titre maison", "Résumé existant"),
    ]
