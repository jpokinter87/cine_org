"""Tests unitaires pour MovieRelinkService (réparation des fiches sans file_path)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.entities.media import Movie
from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.infrastructure.persistence.models import MovieModel
from src.services.relink_service import FoundFile, MovieRelinkService
from src.services.renamer import generate_movie_filename


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


def test_relink_creates_formatted_symlink_for_raw_storage_file(
    session, tmp_path, extractor, media_info
):
    """Cas (c) : fichier brut dans storage, aucun symlink → symlink canonique créé."""
    # Storage avec un nom de fichier brut (non formaté)
    storage_dir = tmp_path / "storage"
    (storage_dir / "Films" / "Drame").mkdir(parents=True)
    raw_file = (
        storage_dir / "Films" / "Drame" / "cria.cuervos.1976.multi.1080p.x264.mkv"
    )
    raw_file.write_bytes(b"fake")

    # video_dir avec le dossier de genre déjà présent
    video_dir = tmp_path / "video"
    (video_dir / "Films" / "Drame").mkdir(parents=True)

    # Fiche sans file_path ni symlink_path
    movie = MovieModel(
        tmdb_id=1,
        title="Cría cuervos",
        original_title="Cría cuervos",
        year=1976,
        genres_json='["Drame"]',
        file_path=None,
        symlink_path=None,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    # Finder : trouve le fichier brut, sans symlink existant (cas c)
    finder = MagicMock()
    finder.find.return_value = FoundFile(storage_path=raw_file, existing_symlink=None)

    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=video_dir,
    )

    outcome = service.relink_movie(movie.id, dry_run=False)

    # file_path pointe sur le fichier storage brut
    session.refresh(movie)
    assert movie.file_path == str(raw_file)

    # symlink créé, pointant vers le fichier brut, au nom canonique formaté
    assert movie.symlink_path is not None
    link = Path(movie.symlink_path)
    assert link.is_symlink()
    assert link.resolve() == raw_file.resolve()

    expected_name = generate_movie_filename(
        Movie(
            title="Cría cuervos",
            original_title="Cría cuervos",
            year=1976,
            genres=("Drame",),
        ),
        media_info,
        ".mkv",
    )
    assert link.name == expected_name
    assert outcome.status == "linked_created"


def test_relink_reuses_existing_formatted_symlink(session, tmp_path, extractor):
    """Cas (a/b) : symlink formaté déjà présent → réutilisé, aucun nouveau créé."""
    storage_dir = tmp_path / "storage"
    (storage_dir / "Films" / "Action & Aventure").mkdir(parents=True)
    target = (
        storage_dir
        / "Films"
        / "Action & Aventure"
        / "Die Hard 4 - Retour en enfer (2007) MULTi x265 1080p.mkv"
    )
    target.write_bytes(b"fake")

    video_dir = tmp_path / "video"
    link_dir = video_dir / "Films" / "Action & Aventure"
    link_dir.mkdir(parents=True)
    existing_link = link_dir / target.name
    existing_link.symlink_to(target)

    movie = MovieModel(
        tmdb_id=2,
        title="Die Hard 4 : Retour en enfer",
        original_title="Live Free or Die Hard",
        year=2007,
        genres_json='["Action & Aventure"]',
        file_path=None,
        symlink_path=None,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    finder = MagicMock()
    finder.find.return_value = FoundFile(
        storage_path=target, existing_symlink=existing_link
    )

    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=video_dir,
    )

    outcome = service.relink_movie(movie.id, dry_run=False)

    session.refresh(movie)
    assert outcome.status == "linked_existing"
    assert movie.file_path == str(target)
    assert movie.symlink_path == str(existing_link)
    # Le symlink existant n'est pas touché et pointe toujours vers la cible
    assert existing_link.is_symlink()
    assert existing_link.resolve() == target.resolve()
    # Aucun MediaInfo nécessaire quand on réutilise un symlink existant
    extractor.extract.assert_not_called()


def test_relink_unresolved_when_no_file_found(session, tmp_path, extractor):
    """Aucun fichier trouvé → statut unresolved, fiche inchangée."""
    movie = MovieModel(
        tmdb_id=3, title="Coquille Vide", year=2024, file_path=None, symlink_path=None
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    finder = MagicMock()
    finder.find.return_value = None

    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=tmp_path / "video",
    )

    outcome = service.relink_movie(movie.id, dry_run=False)

    session.refresh(movie)
    assert outcome.status == "unresolved"
    assert movie.file_path is None
    assert movie.symlink_path is None


def test_dry_run_does_not_touch_db_or_filesystem(session, tmp_path, extractor):
    """Dry-run : aucun symlink créé, aucune écriture en base."""
    storage_dir = tmp_path / "storage"
    (storage_dir / "Films" / "Drame").mkdir(parents=True)
    raw_file = storage_dir / "Films" / "Drame" / "cube.1997.x264.mkv"
    raw_file.write_bytes(b"fake")

    video_dir = tmp_path / "video"
    (video_dir / "Films" / "Drame").mkdir(parents=True)

    movie = MovieModel(
        tmdb_id=4,
        title="Cube",
        year=1997,
        genres_json='["Drame"]',
        file_path=None,
        symlink_path=None,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    finder = MagicMock()
    finder.find.return_value = FoundFile(storage_path=raw_file, existing_symlink=None)

    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=video_dir,
    )

    outcome = service.relink_movie(movie.id, dry_run=True)

    session.refresh(movie)
    assert outcome.status == "linked_created"
    # Rien n'est persisté en base
    assert movie.file_path is None
    assert movie.symlink_path is None
    # Aucun symlink créé sur le disque
    assert not any((video_dir / "Films" / "Drame").iterdir())


def test_link_chosen_applies_user_selected_file(
    session, tmp_path, extractor, media_info
):
    """link_chosen() lie une fiche au fichier choisi par l'utilisateur (cas litigieux)."""
    storage_dir = tmp_path / "storage"
    (storage_dir / "Films" / "Drame").mkdir(parents=True)
    chosen = storage_dir / "Films" / "Drame" / "vol.captain.2021.x264.mkv"
    chosen.write_bytes(b"fake")

    video_dir = tmp_path / "video"
    (video_dir / "Films" / "Drame").mkdir(parents=True)

    movie = MovieModel(
        tmdb_id=9,
        title="Le capitaine Volkonogov",
        year=2023,
        genres_json='["Drame"]',
        file_path=None,
        symlink_path=None,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)

    finder = MagicMock()  # non utilisé par link_chosen
    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=video_dir,
    )

    outcome = service.link_chosen(
        movie.id, chosen, media_info=media_info, dry_run=False
    )

    session.refresh(movie)
    assert outcome.status == "linked_created"
    assert movie.file_path == str(chosen)
    assert movie.symlink_path is not None
    link = Path(movie.symlink_path)
    assert link.is_symlink()
    assert link.resolve() == chosen.resolve()


def test_relink_unlinked_processes_only_null_file_path(session, tmp_path, extractor):
    """relink_unlinked ne traite que les fiches sans file_path."""
    storage_dir = tmp_path / "storage"
    (storage_dir / "Films" / "Drame").mkdir(parents=True)
    raw_file = storage_dir / "Films" / "Drame" / "film.x264.mkv"
    raw_file.write_bytes(b"fake")
    video_dir = tmp_path / "video"
    (video_dir / "Films" / "Drame").mkdir(parents=True)

    null_movie = MovieModel(
        tmdb_id=5,
        title="Sans Fichier",
        year=2020,
        genres_json='["Drame"]',
        file_path=None,
        symlink_path=None,
    )
    linked_movie = MovieModel(
        tmdb_id=6,
        title="Déjà Lié",
        year=2021,
        genres_json='["Drame"]',
        file_path="/media/storage/deja.mkv",
    )
    session.add(null_movie)
    session.add(linked_movie)
    session.commit()
    session.refresh(null_movie)

    finder = MagicMock()
    finder.find.return_value = FoundFile(storage_path=raw_file, existing_symlink=None)

    service = MovieRelinkService(
        session=session,
        media_info_extractor=extractor,
        finder=finder,
        video_dir=video_dir,
    )

    outcomes = service.relink_unlinked(dry_run=False)

    # Une seule fiche traitée (celle sans file_path)
    assert len(outcomes) == 1
    assert outcomes[0].movie_id == null_movie.id
    assert outcomes[0].status == "linked_created"
