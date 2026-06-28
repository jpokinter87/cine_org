"""Tests de la construction de l'arbre Jellyfin."""

from src.services.jellyfin.tree_builder import (
    ensure_symlink,
    episode_filename,
    folder_name,
    resolve_source,
)


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


def test_resolve_returns_none_for_broken_symlink(tmp_path):
    target = tmp_path / "target.mkv"
    target.write_text("x")
    link = tmp_path / "link.mkv"
    link.symlink_to(target)
    target.unlink()  # brise le symlink

    assert resolve_source(str(link), None) is None


def test_folder_name_with_year():
    assert folder_name("Inception", 2010) == "Inception (2010)"


def test_folder_name_without_year():
    assert folder_name("Sans Année", None) == "Sans Année"


def test_folder_name_with_tmdb_suffix():
    assert (
        folder_name("Doublon", 2010, tmdb_id=42, with_id=True)
        == "Doublon (2010) [tmdbid-42]"
    )


def test_folder_name_sanitizes_illegal_chars():
    out = folder_name("A: B/C", 2020)
    assert ":" not in out and "/" not in out
    assert out.endswith("(2020)")


def test_episode_filename():
    assert (
        episode_filename("12 Monkeys", 2015, 1, 3, ".mkv")
        == "12 Monkeys (2015) S01E03.mkv"
    )


def test_ensure_symlink_creates_and_is_idempotent(tmp_path):
    target = tmp_path / "phys.mkv"
    target.write_text("x")
    link = tmp_path / "sub" / "dir" / "link.mkv"

    ensure_symlink(target, link)
    assert link.is_symlink()
    assert link.resolve() == target.resolve()

    ensure_symlink(target, link)  # rejouer : ne lève pas, lien inchangé
    assert link.resolve() == target.resolve()


def test_ensure_symlink_replaces_wrong_target(tmp_path):
    old = tmp_path / "old.mkv"
    old.write_text("o")
    new = tmp_path / "new.mkv"
    new.write_text("n")
    link = tmp_path / "link.mkv"
    link.symlink_to(old)

    ensure_symlink(new, link)
    assert link.resolve() == new.resolve()


def test_ensure_symlink_replaces_regular_file(tmp_path):
    target = tmp_path / "target.mkv"
    target.write_text("x")
    link = tmp_path / "link.mkv"
    link.write_text("fichier ordinaire")  # pas un symlink

    ensure_symlink(target, link)

    assert link.is_symlink()
    assert link.resolve() == target.resolve()


def test_ensure_symlink_replaces_directory(tmp_path):
    target = tmp_path / "target.mkv"
    target.write_text("x")
    link = tmp_path / "link.mkv"
    link.mkdir()  # un répertoire à la place du lien attendu
    (link / "parasite.txt").write_text("résidu")

    ensure_symlink(target, link)

    assert link.is_symlink()
    assert link.resolve() == target.resolve()
