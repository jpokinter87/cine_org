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
    organizer.get_movie_video_destination.return_value = (
        video_dir / "Films" / "Science-Fiction" / "A"
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
    """L'entité Movie + symlink_path canonique sont cachés pour finalize."""
    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(movie_in_db=existing)
    finalizer._organizer.get_movie_video_destination.return_value = Path(
        "/new_video/Films/Science-Fiction/A"
    )
    item = _raw_movie_item(item_id="cache-key", tmdb_id=19995)

    finalizer.prepare(item)

    assert "cache-key" in finalizer._movie_cache
    cached = finalizer._movie_cache["cache-key"]
    assert cached.movie.id == "42"
    assert cached.symlink_path == Path(
        "/new_video/Films/Science-Fiction/A/Avatar (2009).mkv"
    )


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


def test_finalize_without_prepare_raises():
    """finalize() sans prepare() préalable → RuntimeError."""
    finalizer = _make_finalizer()
    item = _raw_movie_item()
    with pytest.raises(RuntimeError, match="prepare"):
        finalizer.finalize(item, Path("/new/Avatar.mkv"))


def test_prepare_movie_refuses_when_existing_movie_points_to_existing_file(
    tmp_path,
):
    """Garde-fou anti-écrasement : si le Movie en DB a déjà un file_path
    pointant vers un fichier existant, prepare() lève FileExistsError pour
    empêcher rsync d'écraser silencieusement la bibliothèque.

    Cas typique attrapé : multi-parts (4 fichiers source → même tmdb_id →
    même destination canonique) ou doublon non détecté en amont par
    LibraryPresenceChecker (ex. Movie inséré pendant l'apply par un autre
    item du plan).
    """
    existing_file = tmp_path / "Avatar (2009).mkv"
    existing_file.write_bytes(b"x")
    existing = Movie(
        id="42",
        tmdb_id=19995,
        title="Avatar",
        year=2009,
        file_path=str(existing_file),
    )
    finalizer = _make_finalizer(movie_in_db=existing)
    item = _raw_movie_item(tmdb_id=19995)

    with pytest.raises(FileExistsError, match="déjà présent"):
        finalizer.prepare(item)


def test_prepare_movie_proceeds_when_existing_movie_file_path_missing(
    tmp_path,
):
    """Si Movie en DB a file_path mais le fichier n'existe plus (cleanup
    incomplet, fichier déplacé), prepare() continue normalement : pas
    d'écrasement réel possible."""
    stale_path = tmp_path / "Avatar (2009).mkv"  # n'existe pas
    existing = Movie(
        id="42",
        tmdb_id=19995,
        title="Avatar",
        year=2009,
        file_path=str(stale_path),
    )
    finalizer = _make_finalizer(movie_in_db=existing)
    item = _raw_movie_item(tmdb_id=19995)

    destination = finalizer.prepare(item)

    assert destination == Path(
        "/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv"
    )


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
    organizer.get_series_video_destination.return_value = (
        video_dir / "Séries" / "L" / "Lost (2004)" / "Saison 01"
    )

    renamer = MagicMock()
    renamer.generate_series_filename.return_value = (
        "Lost (2004) - S01E01.mkv"
    )

    episode_repo = MagicMock()
    episode_repo.get_by_series.return_value = []
    episode_repo.save.side_effect = lambda e: type(e)(
        id="11" if e.id is None else e.id,
        series_id=e.series_id,
        season_number=e.season_number,
        episode_number=e.episode_number,
        title=e.title,
    )

    return MigrationRawFinalizer(
        tmdb_client=tmdb,
        tvdb_client=tvdb,
        movie_repo=movie_repo,
        series_repo=series_repo,
        episode_repo=episode_repo,
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
    """Series + Episode synthétique + symlink_path cachés pour finalize."""
    existing = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer = _make_series_finalizer(series_in_db=existing)
    item = _raw_series_item(item_id="cache-ser", tvdb_id=73739)

    finalizer.prepare(item)

    assert "cache-ser" in finalizer._series_cache
    cached = finalizer._series_cache["cache-ser"]
    assert cached.series.id == "7"
    assert cached.episode.season_number == 1
    assert cached.episode.episode_number == 1
    assert cached.symlink_path == Path(
        "/new_video/Séries/L/Lost (2004)/Saison 01/Lost (2004) - S01E01.mkv"
    )


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


# ---- finalize() films + séries (étape 4b3) ------------------------------


def _setup_real_filesystem(tmp_path):
    """Crée une arborescence réelle pour tester symlink + delete physiques."""
    source = tmp_path / "old_nas" / "Films" / "Avatar (2009).mkv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"AVATAR_BIN" * 100)

    storage_dir = tmp_path / "new_storage"
    video_dir = tmp_path / "new_video"
    storage_dir.mkdir()
    video_dir.mkdir()

    destination = storage_dir / "Films" / "Science-Fiction" / "A" / "Avatar (2009).mkv"
    destination.parent.mkdir(parents=True)
    # Simule rsync : la destination existe et a le contenu source.
    destination.write_bytes(source.read_bytes())

    return {
        "source": source,
        "destination": destination,
        "storage_dir": storage_dir,
        "video_dir": video_dir,
    }


def test_finalize_movie_creates_symlink_updates_db_and_deletes_source(
    tmp_path,
):
    """End-to-end finalize films : symlink + DB paths + suppression source."""
    fs = _setup_real_filesystem(tmp_path)
    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)

    finalizer = _make_finalizer(
        movie_in_db=existing,
        storage_dir=fs["storage_dir"],
        video_dir=fs["video_dir"],
    )
    finalizer._organizer.get_movie_destination.return_value = (
        fs["storage_dir"] / "Films" / "Science-Fiction" / "A"
    )
    finalizer._organizer.get_movie_video_destination.return_value = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A"
    )

    # On ne teste pas la session DB ici : on patche _update_movie_paths
    # pour vérifier l'appel sans dépendre d'une vraie DB.
    finalizer._update_movie_paths = MagicMock()

    item = _raw_movie_item(
        item_id="m1", tmdb_id=19995, source=fs["source"]
    )
    finalizer.prepare(item)
    finalizer.finalize(item, fs["destination"])

    expected_symlink = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A" / "Avatar (2009).mkv"
    )
    assert expected_symlink.is_symlink()
    assert expected_symlink.resolve() == fs["destination"].resolve()
    assert not fs["source"].exists()
    finalizer._update_movie_paths.assert_called_once_with(
        42,
        file_path=str(fs["destination"]),
        symlink_path=str(expected_symlink),
    )


def test_finalize_movie_idempotent_when_source_already_deleted(tmp_path):
    """Reprise après crash : si la source est déjà absente, finalize est silencieux."""
    fs = _setup_real_filesystem(tmp_path)
    fs["source"].unlink()  # source déjà supprimée par un run précédent

    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(
        movie_in_db=existing,
        storage_dir=fs["storage_dir"],
        video_dir=fs["video_dir"],
    )
    finalizer._organizer.get_movie_destination.return_value = (
        fs["storage_dir"] / "Films" / "Science-Fiction" / "A"
    )
    finalizer._organizer.get_movie_video_destination.return_value = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A"
    )
    finalizer._update_movie_paths = MagicMock()

    item = _raw_movie_item(item_id="m2", tmdb_id=19995, source=fs["source"])
    finalizer.prepare(item)
    # Pas d'exception attendue.
    finalizer.finalize(item, fs["destination"])

    expected_symlink = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A" / "Avatar (2009).mkv"
    )
    assert expected_symlink.is_symlink()


def test_finalize_movie_replaces_existing_symlink(tmp_path):
    """Si un symlink existe déjà au même path (reprise), il est remplacé."""
    fs = _setup_real_filesystem(tmp_path)
    expected_symlink = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A" / "Avatar (2009).mkv"
    )
    expected_symlink.parent.mkdir(parents=True)
    # Crée un symlink résiduel pointant ailleurs.
    other_target = fs["storage_dir"] / "ailleurs.mkv"
    other_target.write_bytes(b"x")
    expected_symlink.symlink_to(other_target)

    existing = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009)
    finalizer = _make_finalizer(
        movie_in_db=existing,
        storage_dir=fs["storage_dir"],
        video_dir=fs["video_dir"],
    )
    finalizer._organizer.get_movie_destination.return_value = (
        fs["storage_dir"] / "Films" / "Science-Fiction" / "A"
    )
    finalizer._organizer.get_movie_video_destination.return_value = (
        fs["video_dir"] / "Films" / "Science-Fiction" / "A"
    )
    finalizer._update_movie_paths = MagicMock()

    item = _raw_movie_item(item_id="m3", tmdb_id=19995, source=fs["source"])
    finalizer.prepare(item)
    finalizer.finalize(item, fs["destination"])

    assert expected_symlink.resolve() == fs["destination"].resolve()


def test_finalize_series_creates_episode_in_db_then_symlink(tmp_path):
    """Finalize séries : episode_repo.save + update_episode_paths + symlink + delete."""
    source = tmp_path / "old" / "Lost.S01E01.mkv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"LOST_BIN")
    storage_dir = tmp_path / "storage"
    video_dir = tmp_path / "video"
    storage_dir.mkdir()
    video_dir.mkdir()
    destination = (
        storage_dir / "Séries" / "L" / "Lost (2004)" / "Saison 01"
        / "Lost (2004) - S01E01.mkv"
    )
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())

    existing = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer = _make_series_finalizer(
        series_in_db=existing,
        storage_dir=storage_dir,
        video_dir=video_dir,
    )
    finalizer._organizer.get_series_destination.return_value = destination.parent
    finalizer._organizer.get_series_video_destination.return_value = (
        video_dir / "Séries" / "L" / "Lost (2004)" / "Saison 01"
    )
    finalizer._update_episode_paths = MagicMock()

    item = _raw_series_item(item_id="s1", tvdb_id=73739, source=source)
    finalizer.prepare(item)
    finalizer.finalize(item, destination)

    expected_symlink = (
        video_dir / "Séries" / "L" / "Lost (2004)" / "Saison 01"
        / "Lost (2004) - S01E01.mkv"
    )
    assert expected_symlink.is_symlink()
    assert expected_symlink.resolve() == destination.resolve()
    assert not source.exists()
    finalizer._episode_repo.save.assert_called_once()
    finalizer._update_episode_paths.assert_called_once()


def test_finalize_series_reuses_existing_episode(tmp_path, monkeypatch):
    """Si l'épisode existe déjà en DB → pas de save() supplémentaire."""
    from src.core.entities.media import Episode

    existing_series = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer = _make_series_finalizer(
        series_in_db=existing_series,
        storage_dir=tmp_path / "storage",
        video_dir=tmp_path / "video",
    )
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "video").mkdir(parents=True, exist_ok=True)
    finalizer._organizer.get_series_destination.return_value = tmp_path / "storage"
    finalizer._organizer.get_series_video_destination.return_value = tmp_path / "video"

    existing_episode = Episode(
        id="55", series_id="7", season_number=1, episode_number=1
    )
    finalizer._episode_repo.get_by_series.return_value = [existing_episode]
    finalizer._update_episode_paths = MagicMock()

    # Source physique réelle pour que _delete_source réussisse.
    source = tmp_path / "src.mkv"
    source.write_bytes(b"x")
    item = _raw_series_item(item_id="s2", tvdb_id=73739, source=source)
    destination = tmp_path / "storage" / "Lost (2004) - S01E01.mkv"
    destination.write_bytes(b"x")

    finalizer.prepare(item)
    finalizer.finalize(item, destination)

    # save n'est PAS appelé : l'épisode existe déjà.
    finalizer._episode_repo.save.assert_not_called()
    # update_episode_paths est appelé avec l'episode existant (id=55).
    finalizer._update_episode_paths.assert_called_once_with(
        55,
        file_path=str(destination),
        symlink_path=str(tmp_path / "video" / "Lost (2004) - S01E01.mkv"),
    )


def test_finalize_series_without_episode_repo_raises():
    """Sans episode_repo, finalize séries → RuntimeError."""
    finalizer = _make_series_finalizer()
    finalizer._episode_repo = None  # désactive l'episode_repo
    existing = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    finalizer._series_repo.get_by_tvdb_id.return_value = existing

    item = _raw_series_item(item_id="s3", tvdb_id=73739)
    finalizer.prepare(item)
    with pytest.raises(RuntimeError, match="episode_repo"):
        finalizer.finalize(item, Path("/x.mkv"))
