"""
Tests pour MigrationRawFinalizer (étapes 4b1 → 4b3).

Étape 4b1 : prepare() pour films uniquement (lookup ou fetch TMDB +
upsert Movie + chemin canonique via organizer/renamer).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Movie, Series
from src.core.ports.api_clients import MediaDetails
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
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


def test_finalize_raises_not_implemented():
    """finalize() sera livré en étape 4b3."""
    finalizer = _make_finalizer()
    item = _raw_movie_item()
    with pytest.raises(NotImplementedError, match="4b3"):
        finalizer.finalize(item, Path("/new/Avatar.mkv"))


# ---- prepare() séries (étape 4b2) ----------------------------------------


def _raw_series_item(
    *,
    item_id: str = "ser1",
    tvdb_id: int | None = 73739,
    tmdb_id: int | None = None,
    source: Path = Path("/old/Séries/Lost.S01E01.mkv"),
    media_root: str = "Séries",
) -> MigrationItem:
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.MIGRATE,
        symlink_path=source,
        source_path=source,
        destination_path=None,
        media_root=media_root,
        relative_category="",
        size_bytes=300_000_000,
        rating=RatingDecision(value=8.0, source="tmdb"),
        match=MatchInfo(tvdb_id=tvdb_id, tmdb_id=tmdb_id, score=92.0),
        is_symlink_source=False,
    )


def _series_details(
    *,
    rid: str = "73739",
    title: str = "Lost",
    year: int = 2004,
    genres: tuple[str, ...] = ("Drame", "Mystère"),
) -> MediaDetails:
    return MediaDetails(
        id=rid,
        title=title,
        year=year,
        genres=genres,
        overview="Crash sur une île mystérieuse",
        vote_average=8.3,
        vote_count=5000,
        is_tv=True,
    )


def _make_series_finalizer(
    *,
    series_in_db: Series | None = None,
    fetched_details: MediaDetails | None = None,
    parsed: ParsedFilename | None = None,
    storage_dir: Path = Path("/new_storage"),
    video_dir: Path = Path("/new_video"),
) -> MigrationRawFinalizer:
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(return_value=None)
    tmdb.get_tv_details = AsyncMock(return_value=fetched_details)

    tvdb = MagicMock()
    tvdb.get_details = AsyncMock(return_value=fetched_details)

    movie_repo = MagicMock()
    movie_repo.get_by_tmdb_id.return_value = None
    movie_repo.save.side_effect = lambda m: m

    series_repo = MagicMock()
    series_repo.get_by_tvdb_id.return_value = series_in_db
    series_repo.get_by_tmdb_id.return_value = series_in_db
    series_repo.save.side_effect = lambda s: Series(
        id="7" if s.id is None else s.id,
        tvdb_id=s.tvdb_id,
        tmdb_id=s.tmdb_id,
        title=s.title,
        year=s.year,
        genres=s.genres,
    )

    parser = MagicMock()
    parser.parse.return_value = parsed or ParsedFilename(
        title="Lost",
        year=2004,
        media_type=MediaType.SERIES,
        season=1,
        episode=1,
    )

    organizer = MagicMock()
    organizer.get_series_destination.return_value = (
        storage_dir / "Séries" / "L" / "Lost (2004)" / "Saison 01"
    )

    renamer = MagicMock()
    renamer.generate_series_filename.return_value = (
        "Lost (2004) - S01E01.mkv"
    )

    return MigrationRawFinalizer(
        tmdb_client=tmdb,
        tvdb_client=tvdb,
        movie_repo=movie_repo,
        series_repo=series_repo,
        organizer=organizer,
        renamer=renamer,
        parser=parser,
        storage_dir=storage_dir,
        video_dir=video_dir,
    )


def test_prepare_series_already_in_db_by_tvdb_id():
    """Series déjà en DB → pas de fetch TVDB/TMDB."""
    existing = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer = _make_series_finalizer(series_in_db=existing)
    item = _raw_series_item(tvdb_id=73739)

    destination = finalizer.prepare(item)

    assert destination == Path(
        "/new_storage/Séries/L/Lost (2004)/Saison 01/Lost (2004) - S01E01.mkv"
    )
    finalizer._series_repo.get_by_tvdb_id.assert_called_once_with(73739)
    finalizer._tvdb.get_details.assert_not_called()
    finalizer._tmdb.get_tv_details.assert_not_called()
    finalizer._series_repo.save.assert_not_called()


def test_prepare_series_not_in_db_fetches_tvdb_and_inserts():
    """Series absente → fetch TVDB (tvdb_id présent) + save."""
    finalizer = _make_series_finalizer(
        series_in_db=None, fetched_details=_series_details()
    )
    item = _raw_series_item(tvdb_id=73739)

    destination = finalizer.prepare(item)

    assert destination is not None
    finalizer._tvdb.get_details.assert_called_once_with("73739")
    finalizer._tmdb.get_tv_details.assert_not_called()
    saved = finalizer._series_repo.save.call_args[0][0]
    assert saved.tvdb_id == 73739
    assert saved.title == "Lost"
    assert saved.year == 2004
    assert saved.genres == ("Drame", "Mystère")


def test_prepare_series_falls_back_to_tmdb_when_no_tvdb_id():
    """Pas de tvdb_id → fetch TMDB get_tv_details."""
    finalizer = _make_series_finalizer(
        series_in_db=None,
        fetched_details=_series_details(rid="4607", title="Lost"),
    )
    item = _raw_series_item(tvdb_id=None, tmdb_id=4607)

    finalizer.prepare(item)

    finalizer._tmdb.get_tv_details.assert_called_once_with("4607")
    finalizer._tvdb.get_details.assert_not_called()


def test_prepare_series_returns_none_when_season_missing():
    """Sans saison/épisode parsable → return None (pas de chemin canonique)."""
    finalizer = _make_series_finalizer(
        parsed=ParsedFilename(
            title="Mystère", media_type=MediaType.SERIES, season=None, episode=None
        )
    )
    item = _raw_series_item()

    assert finalizer.prepare(item) is None


def test_prepare_series_caches_for_finalize():
    """Series + Episode synthétique cachés pour finalize() (idempotence)."""
    existing = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer = _make_series_finalizer(series_in_db=existing)
    item = _raw_series_item(item_id="cache-ser", tvdb_id=73739)

    finalizer.prepare(item)

    assert "cache-ser" in finalizer._series_cache
    cached = finalizer._series_cache["cache-ser"]
    assert cached.series.id == "7"
    assert cached.episode.season_number == 1
    assert cached.episode.episode_number == 1


def test_prepare_series_routed_by_media_root_heuristic():
    """media_root='Séries' avec match TMDB 'tmdb' (pas tmdb_tv) → traité comme série."""
    existing = Series(id="7", tmdb_id=4607, title="Lost", year=2004)
    finalizer = _make_series_finalizer(series_in_db=existing)
    item = _raw_series_item(
        tvdb_id=None,
        tmdb_id=4607,
        media_root="Séries",
    )

    destination = finalizer.prepare(item)

    assert destination is not None
    finalizer._series_repo.get_by_tmdb_id.assert_called_with(4607)
    # Pas de routage vers Movie.
    finalizer._movie_repo.get_by_tmdb_id.assert_not_called()


def test_prepare_series_without_repo_raises():
    """Si le finalizer n'a pas series_repo configuré → RuntimeError."""
    # Construit un finalizer "films-only" sans series_repo
    finalizer = _make_finalizer()
    item = _raw_series_item()
    with pytest.raises(RuntimeError, match="series_repo"):
        finalizer.prepare(item)
