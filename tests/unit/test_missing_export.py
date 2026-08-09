"""Tests de l'export de la liste des épisodes manquants.

L'inventaire des manques sert à préparer une session de mise à jour : chaque
ligne dit quoi chercher (série, code d'épisode) et dans quelle qualité.
"""

import csv
import io
import json

from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.missing_export import (
    MissingEntry,
    build_missing_entries,
    format_entries,
)


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _series(
    session,
    title="Terra Nova",
    year=2011,
    status="incomplete",
    missing_episodes=None,
    missing_seasons=None,
    owned=3,
    season=1,
    resolution="1920x1080",
):
    """Crée une série avec son verdict de complétude et des épisodes détenus."""
    series = SeriesModel(
        title=title,
        year=year,
        tvdb_id=1,
        completeness_status=status,
        completeness_missing_json=json.dumps(
            {
                "missing_seasons": missing_seasons or [],
                "missing_episodes": missing_episodes or [],
                "expected_aired": owned + len(missing_episodes or []),
                "owned": owned,
                "source": "tvdb",
            }
        ),
    )
    session.add(series)
    session.commit()
    session.refresh(series)
    for number in range(1, owned + 1):
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=season,
                episode_number=number,
                title=f"Épisode {number}",
                resolution=resolution,
                codec_video="x264",
                languages_json='["fr", "en"]',
                file_path=f"/storage/s{season:02d}e{number:02d}.mkv",
            )
        )
    session.commit()
    return series.id


# --- Construction des entrées ---------------------------------------------


def test_entries_carry_the_target_quality():
    """Chaque manque porte la qualité du reste de la saison."""
    engine = _make_engine()
    with Session(engine) as session:
        _series(
            session,
            missing_episodes=[
                {
                    "season": 1,
                    "episode": 4,
                    "air_date": "2011-12-19",
                    "title": "L'Occupation",
                }
            ],
        )
        entries = build_missing_entries(session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.series_title == "Terra Nova"
    assert entry.series_year == 2011
    assert entry.code == "S01E04"
    assert entry.episode_title == "L'Occupation"
    assert entry.air_date == "2011-12-19"
    assert entry.quality == "1080p · x264 · FR + EN"


def test_entries_include_entirely_missing_seasons():
    """Une saison absente donne une entrée dédiée, sans numéro d'épisode."""
    engine = _make_engine()
    with Session(engine) as session:
        _series(session, missing_seasons=[2])
        entries = build_missing_entries(session)

    assert len(entries) == 1
    assert entries[0].code == "Saison 02"
    assert entries[0].is_whole_season is True


def test_entries_skip_complete_series():
    """Une série complète n'apparaît pas dans l'inventaire."""
    engine = _make_engine()
    with Session(engine) as session:
        _series(session, status="complete")
        assert build_missing_entries(session) == []


def test_entries_can_be_filtered_by_series():
    """Le filtre par identifiant restreint l'inventaire."""
    engine = _make_engine()
    with Session(engine) as session:
        kept = _series(
            session, missing_episodes=[{"season": 1, "episode": 4, "title": "A"}]
        )
        _series(
            session,
            title="Autre",
            missing_episodes=[{"season": 1, "episode": 9, "title": "B"}],
        )
        entries = build_missing_entries(session, series_ids=[kept])

    assert [e.series_title for e in entries] == ["Terra Nova"]


def test_entries_sorted_by_series_then_episode():
    """L'inventaire est trié par série puis par ordre de diffusion."""
    engine = _make_engine()
    with Session(engine) as session:
        _series(
            session,
            title="Zoulou",
            missing_episodes=[{"season": 2, "episode": 1, "title": "z"}],
        )
        _series(
            session,
            title="Alpha",
            missing_episodes=[
                {"season": 1, "episode": 9, "title": "a9"},
                {"season": 1, "episode": 4, "title": "a4"},
            ],
        )
        entries = build_missing_entries(session)

    assert [(e.series_title, e.code) for e in entries] == [
        ("Alpha", "S01E04"),
        ("Alpha", "S01E09"),
        ("Zoulou", "S02E01"),
    ]


def test_entry_without_quality_stays_exportable():
    """Une série sans métadonnées reste listée, sans qualité cible."""
    engine = _make_engine()
    with Session(engine) as session:
        _series(
            session,
            missing_episodes=[{"season": 1, "episode": 4, "title": "A"}],
            resolution=None,
        )
        for episode in session.exec(select(EpisodeModel)).all():
            episode.codec_video = None
            episode.languages_json = None
            session.add(episode)
        session.commit()
        entries = build_missing_entries(session)

    assert len(entries) == 1
    assert entries[0].quality == ""


# --- Formats de sortie ----------------------------------------------------


def _entry(**kwargs):
    base = dict(
        series_title="Terra Nova",
        series_year=2011,
        season=1,
        episode=11,
        episode_title="L'Occupation",
        air_date="2011-12-19",
        quality="1080p · x264 · FR + EN",
    )
    base.update(kwargs)
    return MissingEntry(**base)


def test_text_format_is_one_searchable_line_per_entry():
    """Le format texte tient sur une ligne, prête à coller dans une recherche."""
    output = format_entries([_entry()], "text")
    assert output == "Terra Nova (2011) S01E11 — 1080p · x264 · FR + EN"


def test_text_format_without_quality():
    """Sans qualité connue, la ligne s'arrête au code d'épisode."""
    output = format_entries([_entry(quality="")], "text")
    assert output == "Terra Nova (2011) S01E11"


def test_text_format_whole_season():
    """Une saison entière est annoncée comme telle."""
    output = format_entries([_entry(episode=None, season=2)], "text")
    assert output.startswith("Terra Nova (2011) Saison 02 (complète)")


def test_csv_format_carries_the_full_detail():
    """Le CSV porte le détail complet, titre d'épisode et date inclus."""
    output = format_entries([_entry()], "csv")
    rows = list(csv.reader(io.StringIO(output)))

    assert rows[0] == [
        "serie",
        "annee",
        "saison",
        "episode",
        "titre",
        "diffusion",
        "qualite",
    ]
    assert rows[1] == [
        "Terra Nova",
        "2011",
        "1",
        "11",
        "L'Occupation",
        "2011-12-19",
        "1080p · x264 · FR + EN",
    ]


def test_empty_export_is_empty_string():
    """Rien à exporter : chaîne vide, pas d'en-tête orphelin."""
    assert format_entries([], "text") == ""
    assert format_entries([], "csv") == ""
