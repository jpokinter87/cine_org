"""Tests pour le helper _build_sandbox_items (maintenance.py)."""

from pathlib import Path

from src.web.routes.maintenance import _build_sandbox_items
from src.services.sandbox_service import SandboxService, REJECTED_SUBDIR


def test_build_sandbox_items_exposes_category_and_kept(tmp_path: Path):
    """_build_sandbox_items expose les champs category et kept_version."""
    storage = tmp_path / "storage"
    downloads = tmp_path / "downloads"
    sandbox = tmp_path / ".sandbox"
    video = tmp_path / "video"
    for d in (storage, downloads):
        d.mkdir()

    # Film présent dans video/ (→ kept_version non None)
    kept = video / "Films" / "Action" / "Heat (1995)" / "Heat (1995) VF.mkv"
    kept.parent.mkdir(parents=True)
    kept.write_text("vf")
    # Rejet dans sandbox correspondant au même film
    rej = sandbox / REJECTED_SUBDIR / "Films" / "Heat (1995)" / "Heat (1995) x265.mkv"
    rej.parent.mkdir(parents=True)
    rej.write_text("x265")

    svc = SandboxService(
        sandbox_dir=sandbox, storage_dir=storage, downloads_dir=downloads
    )
    items = _build_sandbox_items(svc, video)

    assert len(items) == 1
    it = items[0]
    assert it["category"] == "rejet_doublon"
    assert it["kept_version"] is not None
    assert "size" in it and it["size_bytes"] == len("x265")


def test_build_sandbox_items_kept_none_when_absent(tmp_path: Path):
    """Un fichier sandboxé sans copie dans video/ a kept_version None."""
    storage = tmp_path / "storage"
    downloads = tmp_path / "downloads"
    sandbox = tmp_path / ".sandbox"
    video = tmp_path / "video"
    for d in (storage, downloads, video):
        d.mkdir()

    rej = sandbox / REJECTED_SUBDIR / "Films" / "Fantome (1999)" / "Fantome (1999).mkv"
    rej.parent.mkdir(parents=True)
    rej.write_text("data")

    svc = SandboxService(
        sandbox_dir=sandbox, storage_dir=storage, downloads_dir=downloads
    )
    items = _build_sandbox_items(svc, video)

    assert len(items) == 1
    assert items[0]["kept_version"] is None
    assert items[0]["category"] == "rejet_doublon"
