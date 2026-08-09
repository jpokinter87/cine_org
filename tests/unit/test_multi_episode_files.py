"""Tests de la prise en charge des fichiers multi-épisodes (SxxE01-E02).

Un seul fichier peut regrouper plusieurs épisodes consécutifs. La colonne
``episode_end`` mémorise le dernier épisode couvert pour que la complétude
ne signale pas à tort les épisodes suivants comme manquants.
"""

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.adapters.cli.helpers import _extract_episode_end
from src.core.entities.media import Episode, Series
from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.database import _backfill_episode_end
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.infrastructure.persistence.repositories.episode_repository import (
    SQLModelEpisodeRepository,
)
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)
from src.services.renamer import generate_series_filename


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


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


# --- Modèle et repository -------------------------------------------------


def test_episode_model_episode_end_defaults_to_none():
    """Un épisode simple n'a pas d'episode_end."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=1)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id, season_number=1, episode_number=1, title="e1"
            )
        )
        session.commit()
        loaded = session.exec(select(EpisodeModel)).first()
        assert loaded.episode_end is None


def test_episode_repository_roundtrips_episode_end():
    """episode_end fait l'aller-retour entité ↔ modèle."""
    engine = _make_engine()
    with Session(engine) as session:
        repo = SQLModelEpisodeRepository(session)
        saved = repo.save(
            Episode(
                series_id="1",
                season_number=1,
                episode_number=1,
                title="Double",
                episode_end=2,
            )
        )
        assert saved.episode_end == 2
        assert repo.get_by_id(saved.id).episode_end == 2


def test_episode_repository_updates_episode_end():
    """La mise à jour d'un épisode existant écrit episode_end."""
    engine = _make_engine()
    with Session(engine) as session:
        repo = SQLModelEpisodeRepository(session)
        saved = repo.save(
            Episode(series_id="1", season_number=1, episode_number=1, title="e1")
        )
        saved.episode_end = 2
        updated = repo.save(saved)
        assert updated.episode_end == 2


# --- Complétude -----------------------------------------------------------


@pytest.mark.asyncio
async def test_double_episode_file_covers_both_numbers():
    """Un fichier S01E01-E02 rend la série complète sur ces deux épisodes."""
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
                file_path="/s/S01E01-E02.mkv",
                episode_end=2,
            )
        )
        session.commit()

        checker = CompletenessChecker(
            _StubTVDB([_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")])
        )
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "complete"
        session.refresh(series)
        assert series.has_missing_episodes is False


@pytest.mark.asyncio
async def test_triple_episode_file_covers_three_numbers():
    """Un fichier S04E19-20-21 couvre les trois épisodes."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=4,
                episode_number=19,
                title="e19",
                file_path="/s/S04E19-20-21.mkv",
                episode_end=21,
            )
        )
        session.commit()

        checker = CompletenessChecker(
            _StubTVDB(
                [
                    _epd(4, 19, "2009-03-06"),
                    _epd(4, 20, "2009-03-20"),
                    _epd(4, 21, "2009-03-20"),
                ]
            )
        )
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "complete"


@pytest.mark.asyncio
async def test_episode_end_without_file_does_not_count():
    """Un episode_end sur une ligne sans fichier ne couvre rien."""
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
                file_path=None,
                episode_end=2,
            )
        )
        session.commit()

        checker = CompletenessChecker(
            _StubTVDB([_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")])
        )
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"


@pytest.mark.asyncio
async def test_episode_end_still_reports_later_gaps():
    """La couverture s'arrête à episode_end : l'épisode suivant reste manquant."""
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
                file_path="/s/S01E01-E02.mkv",
                episode_end=2,
            )
        )
        session.commit()

        checker = CompletenessChecker(
            _StubTVDB(
                [
                    _epd(1, 1, "2019-01-01"),
                    _epd(1, 2, "2019-01-08"),
                    _epd(1, 3, "2019-01-15"),
                ]
            )
        )
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"
        assert '"episode": 3' in series.completeness_missing_json


# --- Renommage ------------------------------------------------------------


def test_series_filename_keeps_episode_range():
    """Le nom canonique conserve la plage SxxExx-Exx."""
    name = generate_series_filename(
        series=Series(title="Terra Nova", year=2011),
        episode=Episode(
            season_number=1, episode_number=1, title="Le Nouveau Monde", episode_end=2
        ),
        media_info=None,
        extension=".mkv",
    )
    assert "S01E01-E02" in name


def test_series_filename_without_range_unchanged():
    """Sans episode_end, le code d'épisode reste simple."""
    name = generate_series_filename(
        series=Series(title="Terra Nova", year=2011),
        episode=Episode(season_number=1, episode_number=3, title="Instinct de vie"),
        media_info=None,
        extension=".mkv",
    )
    assert "S01E03" in name
    assert "-E" not in name.split(" - ")[1]


def test_series_filename_ignores_non_increasing_range():
    """Un episode_end incohérent (<= episode_number) est ignoré."""
    name = generate_series_filename(
        series=Series(title="X"),
        episode=Episode(season_number=1, episode_number=5, title="", episode_end=5),
        media_info=None,
        extension=".mkv",
    )
    assert "S01E05" in name
    assert "S01E05-E05" not in name


def test_series_renamer_entity_keeps_episode_end():
    """La conversion modèle → entité du renommage de série garde la plage."""
    from src.services.series_renamer import _to_episode_entity

    entity = _to_episode_entity(
        EpisodeModel(
            id=1,
            series_id=1,
            season_number=1,
            episode_number=1,
            episode_end=2,
            title="Double",
        )
    )
    assert entity.episode_end == 2


# --- Extraction depuis le nom de fichier ----------------------------------


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (1, 2, 2),
        (19, 21, 21),
        (1, 4, 4),  # plage de 4 épisodes : limite acceptée
        (1, 5, None),  # au-delà de la limite
        (28, 40, None),
        (5, 5, None),
        (5, 3, None),
        (None, 2, None),
        (1, None, None),
    ],
)
def test_resolve_episode_end(start, end, expected):
    """Le garde-fou n'accepte que les plages croissantes et plausibles."""
    from src.utils.helpers import resolve_episode_end

    assert resolve_episode_end(start, end) == expected


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Terra Nova - S01E01-02 - MULTi 1080p.mkv", 2),
        ("Sleepy.Hollow.S01E12-E13.FiNAL.FRENCH.720p.x264.mkv", 13),
        ("BSG.S04E19-20-21.MULTi.1080p.BluRay.x265.mkv", 21),
        ("Terra.Nova.S01E03.MULTi.1080p.WEB.x264-CiELOS.mkv", None),
        # Faux positif à écarter : « E28-40 détectives » n'est pas une plage.
        ("Hitchcock Presente S05E28-40 detectives plus tard.mkv", None),
    ],
)
def test_extract_episode_end(filename, expected):
    """L'extraction ne retient que les plages plausibles."""
    assert _extract_episode_end(filename) == expected


# --- Backfill (Migration 15) ----------------------------------------------


def test_backfill_episode_end_from_file_paths():
    """Le backfill remplit episode_end depuis les noms de fichiers existants."""
    engine = _make_engine()
    with Session(engine) as session:
        session.add_all(
            [
                EpisodeModel(
                    series_id=1,
                    season_number=1,
                    episode_number=1,
                    title="double",
                    file_path="/s/Terra Nova - S01E01-02 - MULTi 1080p.mkv",
                ),
                EpisodeModel(
                    series_id=1,
                    season_number=4,
                    episode_number=19,
                    title="triple",
                    file_path="/s/BSG.S04E19-20-21.MULTi.1080p.mkv",
                ),
                EpisodeModel(
                    series_id=1,
                    season_number=1,
                    episode_number=3,
                    title="simple",
                    file_path="/s/Terra.Nova.S01E03.MULTi.1080p.mkv",
                ),
                EpisodeModel(
                    series_id=1,
                    season_number=5,
                    episode_number=28,
                    title="faux positif",
                    file_path="/s/Hitchcock Presente S05E28-40 detectives.mkv",
                ),
                EpisodeModel(
                    series_id=1,
                    season_number=2,
                    episode_number=1,
                    title="sans fichier",
                    file_path=None,
                ),
            ]
        )
        session.commit()

    with engine.begin() as conn:
        _backfill_episode_end(conn)

    with Session(engine) as session:
        rows = {
            e.title: e.episode_end for e in session.exec(select(EpisodeModel)).all()
        }
    assert rows["double"] == 2
    assert rows["triple"] == 21
    assert rows["simple"] is None
    assert rows["faux positif"] is None
    assert rows["sans fichier"] is None


def test_backfill_episode_end_preserves_existing_values():
    """Une valeur déjà renseignée n'est pas écrasée par le backfill."""
    engine = _make_engine()
    with Session(engine) as session:
        session.add(
            EpisodeModel(
                series_id=1,
                season_number=1,
                episode_number=1,
                title="deja",
                file_path="/s/Show S01E01-02.mkv",
                episode_end=3,
            )
        )
        session.commit()

    with engine.begin() as conn:
        _backfill_episode_end(conn)

    with Session(engine) as session:
        assert session.exec(select(EpisodeModel)).first().episode_end == 3
