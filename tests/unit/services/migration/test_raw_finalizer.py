"""
Tests pour MigrationRawFinalizer (étapes 4b1 → 4b3).

Étape 4b1 : prepare() pour films uniquement (lookup ou fetch TMDB +
upsert Movie + chemin canonique via organizer/renamer).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Movie
from src.core.ports.api_clients import MediaDetails
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    RatingDecision,
)
from src.services.migration.raw_finalizer import MigrationRawFinalizer


# ---- Fixtures -------------------------------------------------------------


def _raw_movie_item(
    *,
    item_id: str = "abc",
    tmdb_id: int | None = 19995,
    source: Path = Path("/old/Films/Avatar (2009).mkv"),
) -> MigrationItem:
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.MIGRATE,
        symlink_path=source,
        source_path=source,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1_000_000_000,
        rating=RatingDecision(value=8.0, source="tmdb"),
        match=MatchInfo(tmdb_id=tmdb_id, score=95.0),
        is_symlink_source=False,
    )


def _media_details(
    *,
    tmdb_id: str = "19995",
    title: str = "Avatar",
    year: int | None = 2009,
    genres: tuple[str, ...] = ("Science-Fiction", "Aventure"),
) -> MediaDetails:
    return MediaDetails(
        id=tmdb_id,
        title=title,
        year=year,
        genres=genres,
        duration_seconds=10000,
        overview="…",
        vote_average=8.0,
        vote_count=10000,
    )


def _make_finalizer(
    *,
    movie_in_db: Movie | None = None,
    fetched_details: MediaDetails | None = None,
    storage_dir: Path = Path("/new_storage"),
    video_dir: Path = Path("/new_video"),
) -> MigrationRawFinalizer:
    """Construit un finalizer avec deps mockées."""
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(return_value=fetched_details)

    movie_repo = MagicMock()
    movie_repo.get_by_tmdb_id.return_value = movie_in_db
    # save retourne le movie avec un id assigné (simulate insert).
    movie_repo.save.side_effect = lambda m: Movie(
        id="42" if m.id is None else m.id,
        tmdb_id=m.tmdb_id,
        title=m.title,
        year=m.year,
        genres=m.genres,
    )

    organizer = MagicMock()
    organizer.get_movie_destination.return_value = (
        storage_dir / "Films" / "Science-Fiction" / "A"
    )

    renamer = MagicMock()
    renamer.generate_movie_filename.return_value = "Avatar (2009).mkv"

    return MigrationRawFinalizer(
        tmdb_client=tmdb,
        movie_repo=movie_repo,
        organizer=organizer,
        renamer=renamer,
        storage_dir=storage_dir,
        video_dir=video_dir,
    )


# ---- prepare() films ------------------------------------------------------


def test_prepare_movie_already_in_db_returns_canonical_destination():
    """Si Movie déjà en DB par tmdb_id : pas de fetch TMDB, lookup direct."""
    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(movie_in_db=existing)
    item = _raw_movie_item(tmdb_id=19995)

    destination = finalizer.prepare(item)

    assert destination == Path(
        "/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv"
    )
    finalizer._movie_repo.get_by_tmdb_id.assert_called_once_with(19995)
    finalizer._tmdb.get_details.assert_not_called()
    finalizer._movie_repo.save.assert_not_called()
    finalizer._organizer.get_movie_destination.assert_called_once()
    finalizer._renamer.generate_movie_filename.assert_called_once()


def test_prepare_movie_not_in_db_fetches_tmdb_and_inserts():
    """Movie absent en DB → fetch TMDB + save + destination canonique."""
    finalizer = _make_finalizer(
        movie_in_db=None, fetched_details=_media_details()
    )
    item = _raw_movie_item(tmdb_id=19995)

    destination = finalizer.prepare(item)

    assert destination == Path(
        "/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv"
    )
    finalizer._tmdb.get_details.assert_called_once_with("19995")
    # save reçoit un Movie construit depuis les details
    save_call = finalizer._movie_repo.save.call_args[0][0]
    assert save_call.tmdb_id == 19995
    assert save_call.title == "Avatar"
    assert save_call.year == 2009
    assert save_call.genres == ("Science-Fiction", "Aventure")


def test_prepare_movie_caches_entity_for_finalize():
    """L'entité Movie est cachée pour l'étape finalize (idempotence)."""
    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(movie_in_db=existing)
    item = _raw_movie_item(item_id="cache-key", tmdb_id=19995)

    finalizer.prepare(item)

    assert "cache-key" in finalizer._movie_cache
    assert finalizer._movie_cache["cache-key"].id == "42"


def test_prepare_returns_none_when_tmdb_id_missing():
    """Sans tmdb_id ni tvdb_id, prepare retourne None (l'item finira en FAILED)."""
    finalizer = _make_finalizer()
    item = _raw_movie_item(tmdb_id=None)

    assert finalizer.prepare(item) is None
    finalizer._tmdb.get_details.assert_not_called()


def test_prepare_returns_none_when_tmdb_fetch_returns_none():
    """Si TMDB ne trouve plus l'œuvre (ID périmé), retourne None."""
    finalizer = _make_finalizer(movie_in_db=None, fetched_details=None)
    item = _raw_movie_item(tmdb_id=19995)

    assert finalizer.prepare(item) is None


def test_prepare_passes_correct_extension_to_renamer():
    """L'extension du fichier source est propagée au renamer."""
    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(movie_in_db=existing)
    item = _raw_movie_item(
        tmdb_id=19995, source=Path("/old/Films/Avatar.mp4")
    )

    finalizer.prepare(item)

    kwargs = finalizer._renamer.generate_movie_filename.call_args.kwargs
    assert kwargs["extension"] == ".mp4"


def test_prepare_raises_not_implemented_for_series():
    """Les séries ne sont pas encore supportées (étape 4b2)."""
    finalizer = _make_finalizer()
    item = _raw_movie_item(tmdb_id=None)
    item.match.tvdb_id = 73739
    with pytest.raises(NotImplementedError, match="séries"):
        finalizer.prepare(item)


def test_prepare_raises_not_implemented_for_series_root_without_id():
    """media_root="Séries" + pas de tmdb_id → NotImplementedError (4b2)."""
    finalizer = _make_finalizer()
    item = _raw_movie_item(tmdb_id=None)
    item.media_root = "Séries"
    with pytest.raises(NotImplementedError, match="séries"):
        finalizer.prepare(item)


def test_finalize_raises_not_implemented():
    """finalize() sera livré en étape 4b3."""
    finalizer = _make_finalizer()
    item = _raw_movie_item()
    with pytest.raises(NotImplementedError, match="4b3"):
        finalizer.finalize(item, Path("/new/Avatar.mkv"))
