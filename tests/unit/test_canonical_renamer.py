"""Tests unitaires pour CanonicalRenamerService."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.infrastructure.persistence.models import MovieModel
from src.services.canonical_renamer import CanonicalRenamerService


@pytest.fixture
def engine():
    """Engine SQLite en mémoire."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def media_info():
    """MediaInfo minimal (1080p, x264, AC3, FR)."""
    return MediaInfo(
        resolution=Resolution(width=1920, height=1080),
        video_codec=VideoCodec(name="x264"),
        audio_codecs=(AudioCodec(name="AC3"),),
        audio_languages=(Language(code="fr", name="Francais"),),
        duration_seconds=5400,
    )


@pytest.fixture
def extractor(media_info):
    ext = MagicMock()
    ext.extract.return_value = media_info
    return ext


@pytest.fixture
def storage_tree(tmp_path):
    """Arborescence storage/video minimale."""
    storage = tmp_path / "storage" / "Films" / "Drame"
    storage.mkdir(parents=True)
    video = tmp_path / "video" / "Films" / "Drame"
    video.mkdir(parents=True)
    return {"storage": storage, "video": video}


def _make_movie(
    session: Session,
    title: str,
    year: int,
    storage_dir: Path,
    filename: str,
    video_dir: Path | None = None,
) -> MovieModel:
    """Crée un fichier factice + symlink + entrée DB."""
    src = storage_dir / filename
    src.write_bytes(b"fake video content")
    symlink_path = None
    if video_dir is not None:
        link = video_dir / filename
        link.symlink_to(src)
        symlink_path = str(link)
    movie = MovieModel(
        tmdb_id=1,
        title=title,
        original_title=title,
        year=year,
        file_path=str(src),
        symlink_path=symlink_path,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)
    return movie


def test_rename_movie_dry_run_reports_new_name(
    session, extractor, storage_tree
):
    """Dry-run : calcule le nom cible sans toucher au filesystem ni à la DB."""
    movie = _make_movie(
        session,
        title="Un condamné à mort s'est échappé",
        year=1956,
        storage_dir=storage_tree["storage"],
        filename="A.Man.Escaped.1956.1080p.BluRay.x264-IGUANA.mkv",
        video_dir=storage_tree["video"],
    )
    service = CanonicalRenamerService(session, extractor)

    outcome = service.rename_movie(movie.id, dry_run=True)

    assert outcome.status == "renamed"
    assert outcome.old_name == "A.Man.Escaped.1956.1080p.BluRay.x264-IGUANA.mkv"
    assert "Un condamné à mort" in outcome.new_name
    assert "(1956)" in outcome.new_name
    assert outcome.new_name.endswith(".mkv")
    # Filesystem intact
    assert outcome.old_storage.exists()
    assert not outcome.new_storage.exists()
    # DB intacte
    session.refresh(movie)
    assert movie.file_path == str(outcome.old_storage)


def test_rename_movie_execute_renames_storage_and_symlink(
    session, extractor, storage_tree
):
    """Exécution : renomme storage, recrée symlink, met à jour DB."""
    movie = _make_movie(
        session,
        title="Les Quatre Cents Coups",
        year=1959,
        storage_dir=storage_tree["storage"],
        filename="The.400.Blows.1959.1080p.BluRay.x264-FSiHD.mkv",
        video_dir=storage_tree["video"],
    )
    old_storage = Path(movie.file_path)
    old_symlink = Path(movie.symlink_path)
    original_inode = old_storage.stat().st_ino
    service = CanonicalRenamerService(session, extractor)

    outcome = service.rename_movie(movie.id, dry_run=False)

    assert outcome.status == "renamed"
    assert not old_storage.exists()
    assert outcome.new_storage.exists()
    # Inode préservée (hardlinks seeding intacts)
    assert outcome.new_storage.stat().st_ino == original_inode
    # Symlink recréé pointant vers new storage
    assert not old_symlink.exists() and not old_symlink.is_symlink()
    assert outcome.new_symlink.is_symlink()
    assert outcome.new_symlink.resolve() == outcome.new_storage.resolve()
    # DB mise à jour
    session.refresh(movie)
    assert movie.file_path == str(outcome.new_storage)
    assert movie.symlink_path == str(outcome.new_symlink)


def test_rename_movie_already_canonical(session, extractor, storage_tree):
    """Si le nom est déjà canonique, aucun renommage."""
    movie = _make_movie(
        session,
        title="Matrix",
        year=1999,
        storage_dir=storage_tree["storage"],
        filename="Matrix (1999) FR x264 1080p.mkv",
        video_dir=storage_tree["video"],
    )
    service = CanonicalRenamerService(session, extractor)

    outcome = service.rename_movie(movie.id, dry_run=True)

    assert outcome.status == "already_canonical"


def test_rename_movie_file_missing(session, extractor, storage_tree):
    """Si le fichier physique n'existe plus, outcome file_missing."""
    movie = MovieModel(
        tmdb_id=1,
        title="Film Fantôme",
        year=2020,
        file_path=str(storage_tree["storage"] / "inexistant.mkv"),
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    service = CanonicalRenamerService(session, extractor)
    outcome = service.rename_movie(movie.id, dry_run=False)

    assert outcome.status == "file_missing"


def test_rename_movie_no_file_path(session, extractor):
    """Si aucun file_path, skip."""
    movie = MovieModel(tmdb_id=1, title="X", year=2020)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    service = CanonicalRenamerService(session, extractor)
    outcome = service.rename_movie(movie.id, dry_run=False)

    assert outcome.status == "no_file_path"


def test_rename_movie_storage_conflict(session, extractor, storage_tree):
    """Si la cible storage existe déjà (fichier différent), conflit."""
    # Fichier source
    movie = _make_movie(
        session,
        title="Titre A",
        year=2020,
        storage_dir=storage_tree["storage"],
        filename="source.mkv",
        video_dir=storage_tree["video"],
    )
    # Fichier cible préexistant
    target = storage_tree["storage"] / "Titre A (2020) FR x264 1080p.mkv"
    target.write_bytes(b"other content")

    service = CanonicalRenamerService(session, extractor)
    outcome = service.rename_movie(movie.id, dry_run=False)

    assert outcome.status == "conflict"
    assert outcome.reason == "storage_target_exists"
    # Le fichier source n'a pas été touché
    assert Path(movie.file_path).exists()


def test_rename_movie_preserves_hardlink(session, extractor, storage_tree, tmp_path):
    """Le hardlink downloads/ reste valide après renommage (inode préservée)."""
    movie = _make_movie(
        session,
        title="Hardlink Test",
        year=2020,
        storage_dir=storage_tree["storage"],
        filename="release.scene.name.mkv",
        video_dir=storage_tree["video"],
    )
    # Simuler le hardlink de seeding
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    download_link = downloads / "release.scene.name.mkv"
    os.link(movie.file_path, download_link)
    assert download_link.stat().st_nlink == 2

    service = CanonicalRenamerService(session, extractor)
    outcome = service.rename_movie(movie.id, dry_run=False)

    assert outcome.status == "renamed"
    # Hardlink toujours valide (pointe vers l'inode, pas le nom)
    assert download_link.exists()
    assert download_link.stat().st_ino == outcome.new_storage.stat().st_ino
    assert download_link.read_bytes() == outcome.new_storage.read_bytes()


def test_rename_movies_batch(session, extractor, storage_tree):
    """Batch : renomme plusieurs films, retourne la liste des outcomes."""
    m1 = _make_movie(
        session, "Film Un", 2020, storage_tree["storage"],
        "film.one.scene.mkv", storage_tree["video"],
    )
    m2 = _make_movie(
        session, "Film Deux", 2021, storage_tree["storage"],
        "film.two.scene.mkv", storage_tree["video"],
    )
    service = CanonicalRenamerService(session, extractor)

    outcomes = service.rename_movies([m1.id, m2.id], dry_run=True)

    assert len(outcomes) == 2
    assert all(o.status == "renamed" for o in outcomes)
