"""Tests pour _trash_source : déplacement d'une source rejetée vers la corbeille."""

from __future__ import annotations

from types import SimpleNamespace

from src.web.routes.transfer import _maybe_trash_source, _trash_source


def test_trash_source_moves_file_and_removes_emptied_parent(tmp_path):
    """Déplace le fichier en corbeille et supprime le dossier parent vidé."""
    downloads = tmp_path / "downloads"
    release = downloads / "Show.S01.GROUP"
    release.mkdir(parents=True)
    ep = release / "Show.S01E01.mkv"
    ep.write_bytes(b"x")
    trash = tmp_path / ".trash"

    dest = _trash_source(ep, trash, downloads_root=downloads)

    assert dest.exists()
    assert dest.parent == trash
    assert dest.read_bytes() == b"x"
    assert not ep.exists()
    # Dossier release vidé → supprimé ; racine downloads préservée
    assert not release.exists()
    assert downloads.exists()


def test_trash_source_keeps_parent_with_remaining_files(tmp_path):
    """Le dossier parent est conservé s'il reste d'autres fichiers."""
    downloads = tmp_path / "downloads"
    release = downloads / "Show.S01.GROUP"
    release.mkdir(parents=True)
    ep1 = release / "Show.S01E01.mkv"
    ep1.write_bytes(b"x")
    ep2 = release / "Show.S01E02.mkv"
    ep2.write_bytes(b"y")
    trash = tmp_path / ".trash"

    _trash_source(ep1, trash, downloads_root=downloads)

    assert not ep1.exists()
    assert ep2.exists()
    assert release.exists()


def test_trash_source_avoids_name_clobber(tmp_path):
    """En cas de nom déjà présent en corbeille, la source est suffixée."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    ep = downloads / "movie.mkv"
    ep.write_bytes(b"new")
    trash = tmp_path / ".trash"
    trash.mkdir()
    (trash / "movie.mkv").write_bytes(b"old")

    dest = _trash_source(ep, trash, downloads_root=downloads)

    assert dest.read_bytes() == b"new"
    assert dest.name != "movie.mkv"
    assert (trash / "movie.mkv").read_bytes() == b"old"  # ancien intact


def _settings(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir(exist_ok=True)
    return SimpleNamespace(storage_dir=tmp_path / "storage", downloads_dir=downloads)


def test_maybe_trash_source_moves_on_keep_old_trash(tmp_path):
    """choix « keep_old_trash » hors dry-run → la source part en corbeille."""
    settings = _settings(tmp_path)
    src = settings.downloads_dir / "movie.mkv"
    src.write_bytes(b"x")

    _maybe_trash_source({"source": src}, "keep_old_trash", settings, dry_run=False)

    assert not src.exists()
    assert (settings.storage_dir / ".trash" / "movie.mkv").exists()


def test_maybe_trash_source_noop_on_keep_old(tmp_path):
    """choix « keep_old » simple → la source reste en place."""
    settings = _settings(tmp_path)
    src = settings.downloads_dir / "movie.mkv"
    src.write_bytes(b"x")

    _maybe_trash_source({"source": src}, "keep_old", settings, dry_run=False)

    assert src.exists()


def test_maybe_trash_source_noop_on_dry_run(tmp_path):
    """dry-run → aucun déplacement même avec keep_old_trash."""
    settings = _settings(tmp_path)
    src = settings.downloads_dir / "movie.mkv"
    src.write_bytes(b"x")

    _maybe_trash_source({"source": src}, "keep_old_trash", settings, dry_run=True)

    assert src.exists()
