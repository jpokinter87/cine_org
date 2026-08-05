"""Tests du rafraîchissement des titres d'épisodes après ré-association.

TMDB est la source primaire des titres, mais il ne fournit pour certaines
séries qu'un gabarit « Épisode N » en fr-FR (cas de *Found : Les Oubliés*).
TVDB, lui, possède les titres français : il sert alors de repli.
"""

import httpx
import pytest
import respx
from sqlmodel import Session, SQLModel, create_engine

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.web.routes.library.reassociate import _refresh_episode_titles

TMDB_URL = "https://api.themoviedb.org/3/tv/214160/season/1/episode/{n}"


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _StubTMDB:
    """Client TMDB réduit à la clé d'API utilisée par l'appel brut."""

    _api_key = "fake-key"


class _StubTVDB:
    def __init__(self, episodes=None):
        self._episodes = episodes or []
        self.calls = 0

    async def get_all_episodes(self, series_id: str):
        self.calls += 1
        return self._episodes


def _tvdb_episode(season: int, number: int, title: str) -> EpisodeDetails:
    return EpisodeDetails(
        id=f"{season}-{number}",
        title=title,
        season_number=season,
        episode_number=number,
        overview=None,
        air_date="2023-10-03",
    )


def _seed(session: Session, *, titles: list[str], tvdb_id: int | None = 423102):
    series = SeriesModel(title="Found : Les Oubliés", year=2023, tvdb_id=tvdb_id)
    session.add(series)
    session.commit()
    session.refresh(series)
    for number, title in enumerate(titles, start=1):
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=number,
                title=title,
                file_path=f"/storage/found/s01e{number:02d}.mkv",
            )
        )
    session.commit()
    return series


def _mock_tmdb(names: list[str | None]) -> None:
    """Programme une réponse TMDB par épisode (None → 404)."""
    for number, name in enumerate(names, start=1):
        route = respx.get(TMDB_URL.format(n=number))
        if name is None:
            route.mock(return_value=httpx.Response(404))
        else:
            route.mock(return_value=httpx.Response(200, json={"name": name}))


@pytest.mark.asyncio
@respx.mock
async def test_titre_tmdb_reel_est_applique():
    """Quand TMDB fournit un vrai titre, il est utilisé et TVDB n'est pas sollicité."""
    with _make_session() as session:
        series = _seed(session, titles=["Weapons of Mass Deduction"])
        _mock_tmdb(["Disparition : une fugueuse"])
        tvdb = _StubTVDB()

        updated = await _refresh_episode_titles(
            session, series, "214160", _StubTMDB(), tvdb
        )

        assert updated == 1
        assert session.get(EpisodeModel, 1).title == "Disparition : une fugueuse"
        assert tvdb.calls == 0


@pytest.mark.asyncio
@respx.mock
async def test_gabarit_tmdb_est_remplace_par_le_titre_tvdb():
    """« Épisode N » n'est pas un titre : on retombe sur TVDB."""
    with _make_session() as session:
        series = _seed(session, titles=["Weapons of Mass Deduction", "Outlaws"])
        _mock_tmdb(["Épisode 1", "Épisode 2"])
        tvdb = _StubTVDB(
            episodes=[
                _tvdb_episode(1, 1, "Disparition : une fugueuse"),
                _tvdb_episode(1, 2, "Disparition : l'escort"),
            ]
        )

        updated = await _refresh_episode_titles(
            session, series, "214160", _StubTMDB(), tvdb
        )

        assert updated == 2
        assert session.get(EpisodeModel, 1).title == "Disparition : une fugueuse"
        assert session.get(EpisodeModel, 2).title == "Disparition : l'escort"
        assert tvdb.calls == 1


@pytest.mark.asyncio
@respx.mock
async def test_gabarit_conserve_si_tvdb_ne_connait_pas_l_episode():
    """Sans titre TVDB, on garde le gabarit TMDB plutôt qu'un titre périmé."""
    with _make_session() as session:
        series = _seed(session, titles=["Weapons of Mass Deduction"])
        _mock_tmdb(["Épisode 1"])
        tvdb = _StubTVDB(episodes=[])

        updated = await _refresh_episode_titles(
            session, series, "214160", _StubTMDB(), tvdb
        )

        assert updated == 1
        assert session.get(EpisodeModel, 1).title == "Épisode 1"


@pytest.mark.asyncio
@respx.mock
async def test_repli_tvdb_ignore_quand_le_tvdb_id_est_inconnu():
    """Sans tvdb_id résolu, aucun appel TVDB n'est tenté."""
    with _make_session() as session:
        series = _seed(session, titles=["Weapons of Mass Deduction"], tvdb_id=None)
        _mock_tmdb(["Épisode 1"])
        tvdb = _StubTVDB(episodes=[_tvdb_episode(1, 1, "Disparition : une fugueuse")])

        await _refresh_episode_titles(session, series, "214160", _StubTMDB(), tvdb)

        assert tvdb.calls == 0
        assert session.get(EpisodeModel, 1).title == "Épisode 1"


@pytest.mark.asyncio
@respx.mock
async def test_episode_absent_de_tmdb_est_complete_par_tvdb():
    """Un 404 TMDB laisse le titre vide : TVDB prend le relais."""
    with _make_session() as session:
        series = _seed(session, titles=["Weapons of Mass Deduction"])
        _mock_tmdb([None])
        tvdb = _StubTVDB(episodes=[_tvdb_episode(1, 1, "Disparition : une fugueuse")])

        updated = await _refresh_episode_titles(
            session, series, "214160", _StubTMDB(), tvdb
        )

        assert updated == 1
        assert session.get(EpisodeModel, 1).title == "Disparition : une fugueuse"
