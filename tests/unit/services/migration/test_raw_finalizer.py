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
    # Par défaut : pas d'imdb_id retourné, pas d'enrichissement IMDb. Les
    # tests qui valident l'enrichissement surchargent ces mocks.
    tmdb.get_external_ids = AsyncMock(return_value=None)

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

    assert destination == Path("/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv")
    finalizer._movie_repo.get_by_tmdb_id.assert_called_once_with(19995)
    finalizer._tmdb.get_details.assert_not_called()
    finalizer._movie_repo.save.assert_not_called()
    finalizer._organizer.get_movie_destination.assert_called_once()
    finalizer._renamer.generate_movie_filename.assert_called_once()


def test_prepare_movie_not_in_db_fetches_tmdb_and_inserts():
    """Movie absent en DB → fetch TMDB + save + destination canonique."""
    finalizer = _make_finalizer(movie_in_db=None, fetched_details=_media_details())
    item = _raw_movie_item(tmdb_id=19995)

    destination = finalizer.prepare(item)

    assert destination == Path("/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv")
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
    item = _raw_movie_item(tmdb_id=19995, source=Path("/old/Films/Avatar.mp4"))

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

    assert destination == Path("/new_storage/Films/Science-Fiction/A/Avatar (2009).mkv")


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
    # Bridge TVDB -> TMDB désactivé par défaut (renvoie None). Les tests
    # qui valident l'enrichissement IMDb surchargent ces mocks.
    tmdb.find_by_tvdb_id = AsyncMock(return_value=None)
    tmdb.get_tv_external_ids = AsyncMock(return_value=None)

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
    renamer.generate_series_filename.return_value = "Lost (2004) - S01E01.mkv"

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


def test_prepare_series_not_in_db_falls_back_to_tvdb_when_no_bridge():
    """Series absente, TMDB ignore le tvdb_id : fallback sur TVDB brut + save.

    Comportement legacy préservé pour les œuvres absentes du catalogue TMDB
    (la série est créée sans note, le transfert continue)."""
    finalizer = _make_series_finalizer(
        series_in_db=None, fetched_details=_series_details()
    )
    # Bridge TMDB inactif par défaut → fallback TVDB.
    item = _raw_series_item(tvdb_id=73739)

    destination = finalizer.prepare(item)

    assert destination is not None
    finalizer._tmdb.find_by_tvdb_id.assert_called_once_with("73739")
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

    item = _raw_movie_item(item_id="m1", tmdb_id=19995, source=fs["source"])
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
        storage_dir
        / "Séries"
        / "L"
        / "Lost (2004)"
        / "Saison 01"
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
        video_dir
        / "Séries"
        / "L"
        / "Lost (2004)"
        / "Saison 01"
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


# ---- Régression : isolation asyncio.run() entre fetches ------------------


class _FakeLoopBoundClient:
    """Stub reproduisant le bug 'Event loop is closed' de httpx.AsyncClient.

    En production, le client httpx (Singleton du Container) est rattaché à
    la 1ère event loop qui l'utilise via son pool de connexions. Quand
    `asyncio.run()` ferme cette loop, les ressources internes (transports,
    sockets) deviennent invalides. Au 2e `asyncio.run()` httpx tente de
    réutiliser une connexion morte → RuntimeError.

    Ce fake reproduit le comportement : `_client` est instancié à la 1ère
    requête dans la loop courante. Si on est rappelé dans une AUTRE loop
    sans que `_client` ait été reset à None, on lève l'exception.
    """

    def __init__(self, details_to_return):
        self._client = None
        self._loop_id = None
        self._details = details_to_return
        self.call_count = 0

    async def _ensure_client_for_loop(self):
        import asyncio

        current_loop_id = id(asyncio.get_running_loop())
        if self._client is None:
            # Instanciation paresseuse dans la loop courante.
            self._client = MagicMock()
            self._client.is_closed = False
            self._client.aclose = AsyncMock()
            self._loop_id = current_loop_id
        elif self._loop_id != current_loop_id:
            raise RuntimeError("Event loop is closed")

    async def get_details(self, media_id):
        self.call_count += 1
        await self._ensure_client_for_loop()
        return self._details

    async def get_tv_details(self, tv_id):
        self.call_count += 1
        await self._ensure_client_for_loop()
        return self._details

    async def find_by_tvdb_id(self, tvdb_id):
        await self._ensure_client_for_loop()
        # Renvoie None par défaut : déclenche le fallback TVDB legacy.
        return None

    async def get_external_ids(self, media_id):
        await self._ensure_client_for_loop()
        return None

    async def get_tv_external_ids(self, tv_id):
        await self._ensure_client_for_loop()
        return None


def test_fetch_movie_details_isolates_httpx_client_across_asyncio_run():
    """Régression : sans isolation entre asyncio.run() successifs, le client
    httpx singleton garde des refs à la loop précédente fermée. Le helper
    doit forcer une recréation à chaque appel pour éviter
    'Event loop is closed'.

    Reproduction du bug observé en production sur `migrate-nas apply` où
    plusieurs items raw consécutifs déclenchaient des fetchs TMDB/TVDB
    séparés (un asyncio.run() par item) et tombaient en alternance
    OK / Event loop is closed / OK / ...
    """
    from src.services.migration.raw_finalizer import _fetch_movie_details

    fake_tmdb = _FakeLoopBoundClient(
        details_to_return=_media_details(tmdb_id="19995", title="Avatar")
    )

    # 1er appel : crée le "client httpx" dans une loop L1 (qui se fermera).
    result1 = _fetch_movie_details(fake_tmdb, 19995)
    assert result1 is not None
    assert result1.title == "Avatar"

    # 2e appel : sans isolation, lèverait 'Event loop is closed' car le
    # client garde une réf à L1 fermée.
    result2 = _fetch_movie_details(fake_tmdb, 19995)
    assert result2 is not None

    # 3e + 4e : confirmer la robustesse (pas juste un coup de chance).
    assert _fetch_movie_details(fake_tmdb, 19995) is not None
    assert _fetch_movie_details(fake_tmdb, 19995) is not None
    assert fake_tmdb.call_count == 4


def test_series_fetch_details_isolates_httpx_client_across_asyncio_run():
    """Idem pour la route séries via tmdb.get_tv_details (cas Exhibit A
    dans la session apply qui a déclenché ce bug)."""
    from src.services.migration.raw_finalizer import _SeriesPreparer

    fake_tmdb = _FakeLoopBoundClient(
        details_to_return=_series_details(rid="90725", title="Exhibit A")
    )
    fake_tvdb = _FakeLoopBoundClient(details_to_return=None)

    preparer = _SeriesPreparer(
        tmdb_client=fake_tmdb,
        tvdb_client=fake_tvdb,
        series_repo=MagicMock(),
        parser=MagicMock(),
        organizer=MagicMock(),
        renamer=MagicMock(),
        storage_dir=Path("/x"),
        video_dir=Path("/y"),
    )

    item = _raw_series_item(tvdb_id=None, tmdb_id=90725)

    # 4 fetchs consécutifs (mêmes que E01..E04 en prod) — tous doivent
    # passer, pas d'alternance OK/Event loop is closed.
    for _ in range(4):
        bundle = preparer._fetch_details_with_ratings(item)
        assert bundle is not None
        details, _ratings, _resolved = bundle
        assert details.title == "Exhibit A"
    assert fake_tmdb.call_count == 4


# ---- Régression : heuristique série robuste au NAS nested ---------------


def test_prepare_routes_as_series_when_media_root_is_nas_parent():
    """Régression : si le scanner pointe au-dessus de Séries/Films (cas NAS
    nested), `media_root` vaut le nom du NAS (ex. 'Vidéothèque10') au lieu
    de 'Séries'. La détection doit alors retomber sur l'inspection du
    chemin (`source_path` / `symlink_path`) pour identifier les épisodes.

    Sans ce fix, un épisode d'Exhibit A dans `.../Vidéothèque10/Séries/...`
    était routé en film → fetch TMDB d'un id série → None silencieux →
    'destination_path manquant'.
    """
    existing = Series(id="7", tmdb_id=90725, title="Exhibit A", year=2019)
    finalizer = _make_series_finalizer(series_in_db=existing)
    item = _raw_series_item(
        tvdb_id=None,
        tmdb_id=90725,
        media_root="Vidéothèque10",  # scanner pointé au-dessus de Séries/
        source=Path(
            "/media/wd/Vidéothèque10/Séries/Exhibit.A.S01/"
            "Exhibit.A.S01E01.DOC.MULTi.1080p.NF.WEB.x264-NEO.mkv"
        ),
    )

    destination = finalizer.prepare(item)

    assert destination is not None
    # Route série : on a touché series_repo, PAS movie_repo.
    finalizer._series_repo.get_by_tmdb_id.assert_called_with(90725)
    finalizer._movie_repo.get_by_tmdb_id.assert_not_called()


# ---- Régression : fallback film quand Animations classée série ----------


def test_prepare_falls_back_to_movie_when_anim_misclassified_as_series():
    """Un film dans Animations/ est classé série par _is_series_item via
    le heuristique 'anim'. Si la route série échoue (parse saison/épisode
    impossible) ET qu'on a un tmdb_id, fallback vers la route film.

    Régression du bug observé sur '[Elecman] Harmony [BDRIP][...].mkv'
    qui finissait en 'destination_path manquant' silencieux.
    """
    finalizer = _make_series_finalizer(
        # parser ne trouve pas saison/épisode → route série retourne None
        parsed=ParsedFilename(
            title="Harmony",
            media_type=MediaType.MOVIE,
            season=None,
            episode=None,
        ),
    )
    # Branche movie : Movie déjà en DB pour court-circuiter le fetch TMDB.
    finalizer._movie_repo.get_by_tmdb_id.return_value = Movie(
        id="99", tmdb_id=460168, title="Harmony", year=2015
    )
    finalizer._organizer.get_movie_destination.return_value = Path(
        "/new_storage/Films/Animation/Adultes/H"
    )
    finalizer._organizer.get_movie_video_destination.return_value = Path(
        "/new_video/Films/Animation/Adultes/H"
    )
    finalizer._renamer.generate_movie_filename.return_value = "Harmony (2015).mkv"

    # Item avec media_root='Animations' (déclenche _is_series_item) + tmdb_id.
    item = _raw_series_item(
        tvdb_id=None,
        tmdb_id=460168,
        media_root="Animations",
        source=Path("/old/Animations/Harmony.mkv"),
    )

    destination = finalizer.prepare(item)

    assert destination == Path(
        "/new_storage/Films/Animation/Adultes/H/Harmony (2015).mkv"
    )
    finalizer._movie_repo.get_by_tmdb_id.assert_called_with(460168)


# ---- Régression : enrichissement notes IMDb/TMDB sur fetch initial ------


class _FakeImdbImporter:
    """Stub IMDbDatasetImporter.get_rating pour les tests d'enrichissement."""

    def __init__(self, ratings: dict[str, tuple[float, int]] | None = None) -> None:
        self._ratings = ratings or {}
        self.calls: list[str] = []

    def get_rating(self, imdb_id: str):
        self.calls.append(imdb_id)
        return self._ratings.get(imdb_id)


def test_prepare_movie_fetches_imdb_id_and_rating_when_importer_present():
    """Le workflow principal peuple imdb_id/imdb_rating/imdb_votes via
    get_external_ids + cache IMDb local. Le finalizer raw doit faire pareil
    sinon les films migrés se retrouvent sans note.
    """
    finalizer = _make_finalizer(movie_in_db=None, fetched_details=_media_details())
    finalizer._tmdb.get_external_ids = AsyncMock(return_value={"imdb_id": "tt0499549"})
    finalizer._imdb_importer = _FakeImdbImporter(
        ratings={"tt0499549": (7.9, 1_350_000)}
    )

    item = _raw_movie_item(tmdb_id=19995)
    finalizer.prepare(item)

    saved = finalizer._movie_repo.save.call_args[0][0]
    assert saved.imdb_id == "tt0499549"
    assert saved.imdb_rating == 7.9
    assert saved.imdb_votes == 1_350_000
    # vote_average TMDB déjà couvert par le test existant.
    assert saved.vote_average == 8.0


def test_prepare_movie_handles_missing_external_ids_gracefully():
    """Si TMDB external_ids échoue ou retourne None, on ne casse pas le
    transfert : imdb_* restent None, le Movie est sauvegardé quand même."""
    finalizer = _make_finalizer(movie_in_db=None, fetched_details=_media_details())
    finalizer._tmdb.get_external_ids = AsyncMock(return_value=None)
    finalizer._imdb_importer = _FakeImdbImporter()

    item = _raw_movie_item(tmdb_id=19995)
    destination = finalizer.prepare(item)

    assert destination is not None
    saved = finalizer._movie_repo.save.call_args[0][0]
    assert saved.imdb_id is None
    assert saved.imdb_rating is None
    assert saved.imdb_votes is None


def test_prepare_series_via_tvdb_bridges_tmdb_for_vote_average_and_imdb():
    """Régression du bug `/media/wd10-2` : une série matchée par tvdb_id
    arrivait sans vote_average (TVDB v3 ne l'expose pas) ni imdb_rating
    (jamais cherché). Le finalizer doit traverser via TMDB
    `find_by_tvdb_id` pour récupérer vote_average + tmdb_id, puis
    `get_tv_external_ids` pour imdb_id, puis le cache IMDb local."""
    finalizer = _make_series_finalizer(series_in_db=None)
    # Le bridge TMDB renvoie un MediaDetails avec id=tmdb_id réel + vote_avg.
    bridged = _series_details(rid="4607", title="Lost", year=2004)
    finalizer._tmdb.find_by_tvdb_id = AsyncMock(return_value=bridged)
    finalizer._tmdb.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt0411008"}
    )
    finalizer._imdb_importer = _FakeImdbImporter(ratings={"tt0411008": (8.3, 540_000)})

    item = _raw_series_item(tvdb_id=73739)
    finalizer.prepare(item)

    saved = finalizer._series_repo.save.call_args[0][0]
    assert saved.tvdb_id == 73739
    assert saved.tmdb_id == 4607  # bridgé depuis MediaDetails.id
    assert saved.vote_average == 8.3
    assert saved.imdb_id == "tt0411008"
    assert saved.imdb_rating == 8.3
    assert saved.imdb_votes == 540_000


def test_prepare_series_via_tvdb_falls_back_to_tvdb_when_bridge_fails():
    """Si TMDB ne connaît pas le tvdb_id (œuvre absente du catalogue), on
    retombe sur les détails TVDB bruts comme avant — la série est
    créée sans note (UNRATED legacy) mais le transfert continue."""
    finalizer = _make_series_finalizer(
        series_in_db=None,
        fetched_details=_series_details(),  # tvdb.get_details renverra ça
    )
    finalizer._tmdb.find_by_tvdb_id = AsyncMock(return_value=None)
    finalizer._tmdb.get_tv_external_ids = AsyncMock(return_value=None)
    finalizer._imdb_importer = _FakeImdbImporter()

    item = _raw_series_item(tvdb_id=73739)
    destination = finalizer.prepare(item)

    assert destination is not None
    finalizer._tvdb.get_details.assert_called_once_with("73739")
    saved = finalizer._series_repo.save.call_args[0][0]
    assert saved.tvdb_id == 73739
    assert saved.imdb_id is None


def test_prepare_series_via_tmdb_enriches_imdb_rating():
    """Pour une série matchée par tmdb_id (sans tvdb_id), on récupère
    aussi imdb_id via get_tv_external_ids + cache IMDb local."""
    finalizer = _make_series_finalizer(
        series_in_db=None,
        fetched_details=_series_details(rid="4607"),
    )
    finalizer._tmdb.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt0411008"}
    )
    finalizer._imdb_importer = _FakeImdbImporter(ratings={"tt0411008": (8.3, 540_000)})

    item = _raw_series_item(tvdb_id=None, tmdb_id=4607)
    finalizer.prepare(item)

    saved = finalizer._series_repo.save.call_args[0][0]
    assert saved.tmdb_id == 4607
    assert saved.imdb_id == "tt0411008"
    assert saved.imdb_rating == 8.3
    assert saved.imdb_votes == 540_000
    assert saved.vote_average == 8.3  # depuis details TMDB
