"""
Tests : la file de validation est vidée des éléments réglés après un transfert web.

Sans ce nettoyage, les éléments transférés restaient « validés » : la page
Transfert les reprenait à l'ouverture suivante et proposait des doublons sur
des fichiers déjà en bibliothèque.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.web.routes.transfer import TransferProgress, _run_web_transfer


def _transfer(tmp_path: Path, name: str, **extra) -> dict:
    source = tmp_path / "downloads" / f"{name}.mkv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"video")
    pending = SimpleNamespace(
        id=f"p-{name}", video_file=SimpleNamespace(id=f"v-{name}")
    )
    return {
        "pending": pending,
        "source": source,
        "destination": tmp_path / "storage" / f"{name}.mkv",
        "symlink_destination": tmp_path / "video" / f"{name}.mkv",
        "new_filename": f"{name}.mkv",
        **extra,
    }


@pytest.fixture
def container(tmp_path):
    c = MagicMock()
    c.config.return_value = SimpleNamespace(
        storage_dir=tmp_path / "storage",
        video_dir=tmp_path / "video",
        downloads_dir=tmp_path / "downloads",
    )
    transferer = c.transferer_service.return_value
    transferer.check_conflict.return_value = None

    def transfer_file(source, destination, **_):
        if "echec" in source.name:
            return SimpleNamespace(success=False, conflict=None, error="disque plein")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return SimpleNamespace(success=True)

    transferer.transfer_file.side_effect = transfer_file
    return c


def _deleted(repo_mock) -> set:
    return {call.args[0] for call in repo_mock.delete.call_args_list}


@pytest.mark.asyncio
async def test_settled_items_leave_queue_errors_stay(container, tmp_path):
    """Succès et « garder l'ancien » sortent de la file ; une erreur y reste."""
    ok = _transfer(tmp_path, "ok")
    echec = _transfer(tmp_path, "echec")
    ancien = _transfer(
        tmp_path,
        "ancien",
        has_duplicate=True,
        duplicate_match=MagicMock(),
        duplicate_resolution="keep_old",
    )

    await _run_web_transfer(container, [ok, echec, ancien], TransferProgress())

    pending_repo = container.pending_validation_repository.return_value
    video_repo = container.video_file_repository.return_value
    assert _deleted(pending_repo) == {"p-ok", "p-ancien"}
    assert _deleted(video_repo) == {"v-ok", "v-ancien"}


@pytest.mark.asyncio
async def test_identical_duplicate_leaves_queue(container, tmp_path):
    """Doublon identique déjà en place (ignoré) : plus rien à faire, sort de la file."""
    from src.services.transferer import ConflictType

    dup = _transfer(tmp_path, "dup")
    container.transferer_service.return_value.check_conflict.return_value = (
        SimpleNamespace(conflict_type=ConflictType.DUPLICATE)
    )

    await _run_web_transfer(container, [dup], TransferProgress())

    pending_repo = container.pending_validation_repository.return_value
    assert _deleted(pending_repo) == {"p-dup"}


@pytest.mark.asyncio
async def test_dry_run_keeps_queue(container, tmp_path):
    """Simulation : la file n'est pas touchée."""
    ok = _transfer(tmp_path, "ok")

    await _run_web_transfer(container, [ok], TransferProgress(), dry_run=True)

    container.pending_validation_repository.return_value.delete.assert_not_called()
