"""Tests de la construction de l'arbre Jellyfin."""

from src.services.jellyfin.tree_builder import resolve_source


def test_resolve_prefers_valid_symlink(tmp_path):
    physical = tmp_path / "phys.mkv"
    physical.write_text("x")
    link = tmp_path / "link.mkv"
    link.symlink_to(physical)

    result = resolve_source(str(link), None)
    assert result == physical.resolve()


def test_resolve_falls_back_to_file_path(tmp_path):
    physical = tmp_path / "phys.mkv"
    physical.write_text("x")
    missing_link = tmp_path / "gone.mkv"  # n'existe pas

    result = resolve_source(str(missing_link), str(physical))
    assert result == physical.resolve()


def test_resolve_returns_none_when_all_missing(tmp_path):
    result = resolve_source(str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv"))
    assert result is None


def test_resolve_handles_none_inputs():
    assert resolve_source(None, None) is None
