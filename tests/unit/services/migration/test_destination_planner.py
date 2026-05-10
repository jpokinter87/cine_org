"""
Tests pour MigrationDestinationPlanner.

Le planner calcule le chemin de destination final d'un candidat sur le nouveau
NAS :

* Si l'œuvre est en DB (movie_id ou series_id fournis par RatingDecision) →
  réutilise OrganizerService + RenamerService pour produire le chemin canonique
  CineOrg (Films/Genre/Lettre/... ou Series/Type/Lettre/Titre (Année)/Saison XX/...).
* Sinon → fallback sur le chemin relatif depuis source_root, conservé tel quel
  sous destination_storage_dir.
* Candidats brisés, déjà sur destination, ou sans target_path → None.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)
from src.services.migration.dataclasses import MigrationCandidate, RatingDecision
from src.services.migration.destination_planner import MigrationDestinationPlanner
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def parser():
    return GuessitFilenameParser()


@pytest.fixture
def organizer():
    return OrganizerService()


@pytest.fixture
def renamer():
    return RenamerService()


@pytest.fixture
def planner(session, parser, organizer, renamer, tmp_path):
    """Planner avec arborescence de destination vide (fallback lettre simple)."""
    storage_dir = tmp_path / "new_storage"
    video_dir = tmp_path / "new_video"
    source_root = Path("/old_nas/Vidéos")
    return MigrationDestinationPlanner(
        session=session,
        parser=parser,
        organizer=organizer,
        renamer=renamer,
        destination_storage_dir=storage_dir,
        destination_video_dir=video_dir,
        source_root=source_root,
    )


_UNSET = object()


def _candidate(
    name: str,
    *,
    media_root: str = "Films",
    relative_category: str = "Drame/D",
    target=_UNSET,
    is_broken: bool = False,
    already_on_destination: bool = False,
) -> MigrationCandidate:
    symlink = Path(f"/old_nas/Vidéos/{media_root}/{relative_category}/{name}")
    if target is _UNSET:
        target = Path(f"/old_storage/{name}")
    return MigrationCandidate(
        symlink_path=symlink,
        target_path=target,
        media_root=media_root,
        relative_category=relative_category,
        is_broken=is_broken,
        already_on_destination=already_on_destination,
    )


# ---- Cas où le planner refuse de produire une destination -------------------


def test_returns_none_for_broken_candidate(planner):
    cand = _candidate(
        "Avatar (2009) FR x265 1080p.mkv",
        target=None,
        is_broken=True,
    )
    assert planner.plan(cand, RatingDecision()) is None


def test_returns_none_when_target_missing(planner):
    cand = _candidate(
        "Avatar (2009) FR x265 1080p.mkv",
        target=None,
    )
    assert planner.plan(cand, RatingDecision()) is None


def test_returns_none_when_already_on_destination(planner):
    cand = _candidate(
        "Avatar (2009) FR x265 1080p.mkv",
        already_on_destination=True,
    )
    assert planner.plan(cand, RatingDecision()) is None


# ---- Cas film en DB --------------------------------------------------------


def test_movie_in_db_uses_canonical_path(session, planner, tmp_path):
    movie = MovieModel(
        tmdb_id=10,
        title="Avatar",
        year=2009,
    )
    movie.genres = ["Science-Fiction", "Action"]
    session.add(movie)
    session.commit()

    decision = RatingDecision(
        value=8.0,
        movie_id_in_db=movie.id,
        title_match="Avatar",
    )
    cand = _candidate("Avatar (2009) FR x265 1080p.mkv")

    result = planner.plan(cand, decision)

    assert result is not None
    # "Science-Fiction" mappe vers le dossier "SF" (cf. GENRE_FOLDER_MAPPING)
    assert result.parent == tmp_path / "new_storage" / "Films" / "SF" / "A"
    # Pas de mediainfo : nom canonique réduit (titre + année + extension)
    assert result.name == "Avatar (2009).mkv"


def test_movie_in_db_preserves_extension_from_symlink(session, planner, tmp_path):
    movie = MovieModel(tmdb_id=20, title="Inception", year=2010)
    movie.genres = ["Science-Fiction"]
    session.add(movie)
    session.commit()

    decision = RatingDecision(value=8.8, movie_id_in_db=movie.id)
    cand = _candidate("Inception (2010) EN x264 720p.avi")

    result = planner.plan(cand, decision)

    assert result is not None
    assert result.suffix == ".avi"


# ---- Cas série en DB ------------------------------------------------------


def test_series_in_db_uses_canonical_path(session, planner, tmp_path):
    series = SeriesModel(tvdb_id=42, title="Sopranos", year=1999)
    series.genres = ["Drame"]
    session.add(series)
    session.commit()

    episode = EpisodeModel(
        series_id=series.id,
        season_number=1,
        episode_number=1,
        title="The Sopranos",
    )
    session.add(episode)
    session.commit()

    decision = RatingDecision(
        value=9.2,
        series_id_in_db=series.id,
        title_match="Sopranos",
    )
    cand = _candidate(
        "Sopranos (1999) - S01E01 - The Sopranos - FR x265 1080p.mkv",
        media_root="Séries",
        relative_category="S",
    )

    result = planner.plan(cand, decision)

    assert result is not None
    # Structure attendue : Series/TV/S/Sopranos (1999)/Saison 01/<filename>
    parts = result.parts
    assert "Series" in parts
    assert "TV" in parts
    assert "Sopranos (1999)" in parts
    assert "Saison 01" in parts
    # Le filename inclut le code épisode et le titre
    assert "S01E01" in result.name
    assert "The Sopranos" in result.name
    assert result.suffix == ".mkv"


def test_series_in_db_without_episode_record_still_uses_canonical_path(
    session, planner, tmp_path
):
    """Si la série est en DB mais l'épisode pas listé, on garde le chemin canonique
    avec un titre d'épisode vide."""
    series = SeriesModel(tvdb_id=43, title="Lost", year=2004)
    series.genres = ["Drame"]
    session.add(series)
    session.commit()

    decision = RatingDecision(value=8.3, series_id_in_db=series.id)
    cand = _candidate(
        "Lost (2004) - S02E05 - FR x265 1080p.mkv",
        media_root="Séries",
        relative_category="L",
    )

    result = planner.plan(cand, decision)

    assert result is not None
    assert "Saison 02" in result.parts
    assert "S02E05" in result.name


def test_series_in_db_falls_back_when_no_season_episode_parsed(
    session, planner, tmp_path
):
    """Si on ne peut pas extraire saison/épisode du nom, on retombe sur le chemin
    relatif depuis source_root."""
    series = SeriesModel(tvdb_id=44, title="Mystery", year=2010)
    series.genres = ["Drame"]
    session.add(series)
    session.commit()

    decision = RatingDecision(value=7.0, series_id_in_db=series.id)
    cand = _candidate(
        "Mystery special.mkv",
        media_root="Séries",
        relative_category="M",
    )

    result = planner.plan(cand, decision)

    # Fallback : destination_storage_dir / chemin relatif depuis source_root
    expected = tmp_path / "new_storage" / "Séries" / "M" / "Mystery special.mkv"
    assert result == expected


# ---- Cas hors DB → fallback chemin relatif ---------------------------------


def test_movie_not_in_db_falls_back_to_relative_path(planner, tmp_path):
    cand = _candidate(
        "ZZZ Inconnu (2050) FR x265 1080p.mkv",
        media_root="Films",
        relative_category="Drame/Z",
    )
    decision = RatingDecision()  # rien en DB

    result = planner.plan(cand, decision)

    expected = (
        tmp_path
        / "new_storage"
        / "Films"
        / "Drame"
        / "Z"
        / "ZZZ Inconnu (2050) FR x265 1080p.mkv"
    )
    assert result == expected


def test_relative_path_fallback_handles_symlink_outside_source_root(planner):
    """Si le symlink n'est pas sous source_root (cas dégénéré), on retourne None."""
    cand = MigrationCandidate(
        symlink_path=Path("/some/where/else/file.mkv"),
        target_path=Path("/old_storage/file.mkv"),
        media_root="Films",
        relative_category="X",
    )
    decision = RatingDecision()

    assert planner.plan(cand, decision) is None
