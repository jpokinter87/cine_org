"""Tests de la ré-évaluation de complétude après ré-association d'une série.

Corriger l'association d'une série invalide son ancien verdict de complétude :
le drapeau « incomplet » et la liste des épisodes manquants portaient sur la
mauvaise fiche. On relance donc une vérification.
"""

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.web.routes.library.reassociate import _refresh_series_completeness


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _episode(season: int, number: int) -> EpisodeDetails:
    return EpisodeDetails(
        id=f"{season}-{number}",
        title=f"S{season}E{number}",
        season_number=season,
        episode_number=number,
        overview=None,
        air_date="2009-12-06",
    )


class _StubTVDB:
    """Client TVDB minimal : résolution par IMDb ID + liste d'épisodes."""

    def __init__(self, tvdb_id=None, episodes=None, raises=False):
        self._tvdb_id = tvdb_id
        self._episodes = episodes or []
        self._raises = raises
        self.resolved_with = None

    async def find_series_id_by_imdb_id(self, imdb_id: str):
        self.resolved_with = imdb_id
        if self._raises:
            raise RuntimeError("TVDB indisponible")
        return self._tvdb_id

    async def get_all_episodes(self, series_id: str):
        return self._episodes


def _seed_series(session: Session, *, owned: int) -> SeriesModel:
    """Série marquée incomplète par l'ancienne (mauvaise) association."""
    series = SeriesModel(
        title="Alice",
        year=2009,
        imdb_id="tt1156398",
        tmdb_id=1234,
        tvdb_id=None,  # invalidé par la ré-association
        completeness_status="incomplete",
        completeness_missing_json='{"missing_seasons": [2, 3, 4]}',
    )
    session.add(series)
    session.commit()
    session.refresh(series)
    for number in range(1, owned + 1):
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=number,
                title=f"E{number}",
                file_path=f"/storage/alice/s01e{number:02d}.mkv",
            )
        )
    session.commit()
    return series


@pytest.mark.asyncio
async def test_refresh_marks_series_complete_when_all_episodes_owned():
    """La nouvelle fiche est complète : le drapeau et le détail sont effacés."""
    with _make_session() as session:
        series = _seed_series(session, owned=2)
        tvdb = _StubTVDB(tvdb_id="87654", episodes=[_episode(1, 1), _episode(1, 2)])

        await _refresh_series_completeness(session, series, tvdb, date(2026, 7, 9))

        assert tvdb.resolved_with == "tt1156398"
        assert series.tvdb_id == 87654
        assert series.completeness_status == "complete"
        assert '"missing_seasons": [2, 3, 4]' not in (
            series.completeness_missing_json or ""
        )


@pytest.mark.asyncio
async def test_refresh_keeps_incomplete_when_episodes_still_missing():
    """Si la nouvelle fiche révèle de vrais manques, le drapeau est conservé."""
    with _make_session() as session:
        series = _seed_series(session, owned=1)
        tvdb = _StubTVDB(tvdb_id="87654", episodes=[_episode(1, 1), _episode(1, 2)])

        await _refresh_series_completeness(session, series, tvdb, date(2026, 7, 9))

        assert series.completeness_status == "incomplete"
        assert '"episode": 2' in series.completeness_missing_json


@pytest.mark.asyncio
async def test_refresh_clears_flag_when_tvdb_id_unresolvable():
    """Sans tvdb_id retrouvé, la série devient non vérifiable : drapeau effacé."""
    with _make_session() as session:
        series = _seed_series(session, owned=1)
        tvdb = _StubTVDB(tvdb_id=None)

        await _refresh_series_completeness(session, series, tvdb, date(2026, 7, 9))

        assert series.tvdb_id is None
        assert series.completeness_status is None
        assert series.completeness_missing_json is None


@pytest.mark.asyncio
async def test_refresh_clears_flag_when_tvdb_fails():
    """Une panne TVDB ne doit pas laisser un verdict périmé sur la fiche."""
    with _make_session() as session:
        series = _seed_series(session, owned=1)
        tvdb = _StubTVDB(raises=True)

        await _refresh_series_completeness(session, series, tvdb, date(2026, 7, 9))

        assert series.completeness_status is None
        assert series.completeness_missing_json is None
