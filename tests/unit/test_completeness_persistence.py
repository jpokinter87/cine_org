"""Tests des colonnes de complétude sur SeriesModel et de leur persistance."""

from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_series_model_has_completeness_columns():
    """Les trois colonnes de complétude existent et sont persistées."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Test", tvdb_id=123)
        series.completeness_status = "incomplete"
        series.completeness_checked_at = datetime(2026, 6, 23, 12, 0, 0)
        series.completeness_missing_json = '{"missing_seasons": [2]}'
        session.add(series)
        session.commit()
        session.refresh(series)

    with Session(engine) as session:
        loaded = session.exec(
            select(SeriesModel).where(SeriesModel.title == "Test")
        ).first()
        assert loaded.completeness_status == "incomplete"
        assert loaded.completeness_checked_at == datetime(2026, 6, 23, 12, 0, 0)
        assert loaded.completeness_missing_json == '{"missing_seasons": [2]}'


def test_completeness_status_defaults_to_none():
    """Une série jamais vérifiée a completeness_status = None."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Neuve")
        session.add(series)
        session.commit()
        session.refresh(series)
        assert series.completeness_status is None
        assert series.completeness_checked_at is None
        assert series.completeness_missing_json is None


def test_series_model_missing_flags_default_false():
    """Les deux flags de granularité valent False par défaut."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Neuve")
        session.add(series)
        session.commit()
        session.refresh(series)
        assert series.has_missing_episodes is False
        assert series.has_missing_seasons is False


def test_series_model_missing_flags_persist():
    """Les deux flags de granularité sont persistés et relus."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Flags", tvdb_id=1)
        series.has_missing_episodes = True
        series.has_missing_seasons = True
        session.add(series)
        session.commit()
    with Session(engine) as session:
        loaded = session.exec(
            select(SeriesModel).where(SeriesModel.title == "Flags")
        ).first()
        assert loaded.has_missing_episodes is True
        assert loaded.has_missing_seasons is True


class _StubTVDB:
    def __init__(self, episodes):
        self._episodes = episodes

    async def get_all_episodes(self, series_id):
        return self._episodes


def _epd(season, episode, air_date):
    return EpisodeDetails(
        id=f"{season}-{episode}",
        title="t",
        season_number=season,
        episode_number=episode,
        overview=None,
        air_date=air_date,
    )


@pytest.mark.asyncio
async def test_check_series_model_persists_incomplete():
    """Une série à qui il manque un épisode diffusé est marquée incomplete."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        # Épisode détenu (1,1) avec fichier ; (1,2) absent.
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path="/storage/s/e1.mkv",
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )

        assert verdict == "incomplete"
        session.refresh(series)
        assert series.completeness_status == "incomplete"
        assert series.completeness_checked_at is not None
        assert '"episode": 2' in series.completeness_missing_json


@pytest.mark.asyncio
async def test_check_series_model_episode_without_file_is_missing():
    """Un épisode sans fichier compte comme manquant."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        # Ligne présente mais SANS fichier → non détenu.
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path=None,
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"


@pytest.mark.asyncio
async def test_check_series_model_extra_episode_ignored():
    """Un épisode is_extra ne compte pas comme détenu."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path="/storage/s/e1.mkv",
                is_extra=True,
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"


@pytest.mark.asyncio
async def test_check_series_model_no_tvdb_id_is_unverifiable():
    """Sans tvdb_id, la série est non vérifiable (status None)."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=None)
        session.add(series)
        session.commit()
        session.refresh(series)

        tvdb = _StubTVDB([])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "unverifiable"
        session.refresh(series)
        assert series.completeness_status is None
        assert series.completeness_checked_at is not None


async def _run_check(session, series, episodes):
    tvdb = _StubTVDB(episodes)
    checker = CompletenessChecker(tvdb)
    await check_series_model(session, checker, series, date(2026, 6, 23))
    session.refresh(series)
    return series


@pytest.mark.asyncio
async def test_flags_episodes_only():
    """Trou d'épisodes dans une saison détenue → has_missing_episodes seul."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id, season_number=1, episode_number=1,
                title="e1", file_path="/s/e1.mkv",
            )
        )
        session.commit()
        # TVDB : (1,1) détenu, (1,2) manquant.
        await _run_check(session, series, [_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")])
        assert series.has_missing_episodes is True
        assert series.has_missing_seasons is False


@pytest.mark.asyncio
async def test_flags_seasons_only():
    """Saison 1 complète, saison 2 entièrement absente → has_missing_seasons seul."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)
        for ep in (1, 2):
            session.add(
                EpisodeModel(
                    series_id=series.id, season_number=1, episode_number=ep,
                    title=f"e{ep}", file_path=f"/s/e{ep}.mkv",
                )
            )
        session.commit()
        # TVDB : saison 1 (1,1),(1,2) détenue ; saison 2 (2,1),(2,2) absente.
        await _run_check(
            session, series,
            [_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08"),
             _epd(2, 1, "2020-01-01"), _epd(2, 2, "2020-01-08")],
        )
        assert series.has_missing_episodes is False
        assert series.has_missing_seasons is True


@pytest.mark.asyncio
async def test_flags_mixed():
    """Trou d'épisodes ET saison entière absente → les deux flags True."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id, season_number=1, episode_number=1,
                title="e1", file_path="/s/e1.mkv",
            )
        )
        session.commit()
        # TVDB : saison 1 (1,1) détenu / (1,2) manquant ; saison 2 (2,1) absente.
        await _run_check(
            session, series,
            [_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08"), _epd(2, 1, "2020-01-01")],
        )
        assert series.has_missing_episodes is True
        assert series.has_missing_seasons is True


@pytest.mark.asyncio
async def test_flags_complete_all_false():
    """Série complète → les deux flags False."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id, season_number=1, episode_number=1,
                title="e1", file_path="/s/e1.mkv",
            )
        )
        session.commit()
        await _run_check(session, series, [_epd(1, 1, "2019-01-01")])
        assert series.completeness_status == "complete"
        assert series.has_missing_episodes is False
        assert series.has_missing_seasons is False


@pytest.mark.asyncio
async def test_flags_reset_when_unverifiable():
    """Une série sans tvdb_id voit ses flags remis à False."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=None)
        series.has_missing_episodes = True
        series.has_missing_seasons = True
        session.add(series)
        session.commit()
        session.refresh(series)
        await _run_check(session, series, [])
        assert series.has_missing_episodes is False
        assert series.has_missing_seasons is False
