"""Tests des opérations sandbox de la route transfert."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.web.routes.transfer import (
    _sandbox_existing,
    _run_web_transfer,
    TransferProgress,
)
from src.services.sandbox_service import (
    REPLACED_SUBDIR,
    SandboxService,
    REJECTED_SUBDIR,
)
from src.services.duplicate_detector import DuplicateMatch


def test_sandbox_existing_movie_goes_to_replaced_subdir(tmp_path: Path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    sandbox = tmp_path / ".sandbox"

    # Film existant dans storage + symlink dans video
    movie_storage = storage / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_storage.mkdir(parents=True)
    real = movie_storage / "Alien (1979) AV1.mkv"
    real.write_text("av1")

    movie_video = video / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_video.mkdir(parents=True)
    (movie_video / "Alien (1979) AV1.mkv").symlink_to(real)

    _sandbox_existing(movie_video, sandbox, storage, video)

    dest = sandbox / REPLACED_SUBDIR / "Films" / "SF" / "A-B" / "Alien (1979)"
    assert dest.exists()
    assert (dest / "Alien (1979) AV1.mkv").exists()
    assert not movie_storage.exists()


def test_sandbox_existing_series_episode_goes_to_replaced_subdir(tmp_path: Path):
    """Vérifie que seul l'épisode ciblé par episode_key est sandboxé (branche série)."""
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    sandbox = tmp_path / ".sandbox"

    # Série existante : 2 épisodes dans storage + symlinks dans video
    season_storage = storage / "Series" / "O" / "Octobre (2021)" / "Saison 01"
    season_storage.mkdir(parents=True)
    ep1 = season_storage / "Octobre (2021) - S01E01 - AV1.mkv"
    ep2 = season_storage / "Octobre (2021) - S01E02 - AV1.mkv"
    ep1.write_text("av1-ep1")
    ep2.write_text("av1-ep2")

    series_video = video / "Series" / "O" / "Octobre (2021)"
    season_video = series_video / "Saison 01"
    season_video.mkdir(parents=True)
    (season_video / ep1.name).symlink_to(ep1)
    (season_video / ep2.name).symlink_to(ep2)

    _sandbox_existing(series_video, sandbox, storage, video, episode_key="S01E01")

    # Seul l'épisode S01E01 part sous anciennes_versions/
    dest1 = (
        sandbox
        / REPLACED_SUBDIR
        / "Series"
        / "O"
        / "Octobre (2021)"
        / "Saison 01"
        / ep1.name
    )
    assert dest1.exists()
    assert dest1.read_text() == "av1-ep1"
    # S01E01 retiré du storage et son symlink supprimé ; S01E02 intact
    assert not ep1.exists()
    assert ep2.exists()
    assert not (season_video / ep1.name).exists()
    assert (season_video / ep2.name).exists()


def _make_container(tmp_path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    downloads = tmp_path / "downloads"
    sandbox = tmp_path / ".sandbox"
    for d in (storage, video, downloads):
        d.mkdir(parents=True, exist_ok=True)

    settings = SimpleNamespace(
        storage_dir=storage,
        video_dir=video,
        downloads_dir=downloads,
        sandbox_dir=sandbox,
        resolved_sandbox_dir=sandbox,
    )
    container = MagicMock()
    container.config.return_value = settings
    container.transferer_service.return_value = MagicMock()
    container.sandbox_service.side_effect = lambda **kw: SandboxService(**kw)
    return container, settings


def test_keep_old_moves_source_to_sandbox(tmp_path):
    container, settings = _make_container(tmp_path)
    src = settings.downloads_dir / "Series" / "Octobre (2021)" / "ep01.mkv"
    src.parent.mkdir(parents=True)
    src.write_text("x265")

    existing_dir = settings.video_dir / "Series" / "Octobre (2021)"
    existing_dir.mkdir(parents=True)

    transfers = [
        {
            "source": src,
            "destination": settings.storage_dir / "Series" / "x" / "ep01.mkv",
            "symlink_destination": None,
            "new_filename": "Octobre (2021) - S01E01 - x265.mkv",
            "is_series": True,
            "has_duplicate": True,
            "duplicate_resolution": "keep_old",
            "duplicate_match": DuplicateMatch(
                existing_dir=existing_dir,
                existing_title="Octobre",
                existing_files=[],
                similarity_reason="même nom",
            ),
            "title": "Octobre",
            "year": 2021,
        }
    ]

    progress = TransferProgress()
    asyncio.run(_run_web_transfer(container, transfers, progress, dry_run=False))

    dest = (
        settings.sandbox_dir
        / REJECTED_SUBDIR
        / "Series"
        / "Octobre (2021)"
        / "ep01.mkv"
    )
    assert dest.exists()
    assert not src.exists()
    # keep_old ne transfère jamais
    container.transferer_service.return_value.transfer_file.assert_not_called()


def test_keep_old_name_collision_moves_source_to_sandbox(tmp_path):
    """Vérifie que keep_old sur un conflit SSE NAME_COLLISION déplace la source en sandbox."""
    container, settings = _make_container(tmp_path)
    src = settings.downloads_dir / "Films" / "Film (2000).mkv"
    src.parent.mkdir(parents=True)
    src.write_text("new")
    dest = settings.storage_dir / "Films" / "Film (2000).mkv"
    dest.parent.mkdir(parents=True)
    dest.write_text("old")

    from src.services.transferer import ConflictInfo, ConflictType

    transferer = container.transferer_service.return_value
    transferer.check_conflict.return_value = ConflictInfo(
        conflict_type=ConflictType.NAME_COLLISION,
        existing_path=dest,
        existing_hash="aaa",
        new_hash="bbb",
    )
    transferer._get_file_info.return_value = SimpleNamespace(
        resolution="1080p", video_codec="x264", audio_codec="AC3"
    )

    transfers = [
        {
            "source": src,
            "destination": dest,
            "symlink_destination": None,
            "new_filename": "Film (2000).mkv",
            "is_series": False,
            "has_duplicate": False,
            "title": "Film",
            "year": 2000,
        }
    ]
    progress = TransferProgress()

    async def _drive():
        task = asyncio.create_task(
            _run_web_transfer(container, transfers, progress, dry_run=False)
        )
        for _ in range(500):
            if progress.conflict_pending:
                break
            await asyncio.sleep(0.01)
        assert progress.conflict_pending, "le conflit aurait dû être en attente"
        progress.conflict_choice = "keep_old"
        progress.conflict_event.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(_drive())

    sandbox_dest = settings.sandbox_dir / REJECTED_SUBDIR / "Films" / "Film (2000).mkv"
    assert sandbox_dest.exists(), f"La source devrait être en sandbox : {sandbox_dest}"
    assert not src.exists(), "La source ne doit plus exister dans downloads/"
    transferer.transfer_file.assert_not_called()
