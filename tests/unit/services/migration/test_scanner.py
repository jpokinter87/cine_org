"""
Tests pour MigrationScanner.

Le scanner parcourt une arborescence de symlinks (source de migration) et
classe chaque entrée vidéo dans un MigrationCandidate avec :
- target_path résolu (en suivant le symlink + recherche dans roots alternatifs)
- is_broken / already_on_destination / is_symlink correctement positionnés
- media_root et relative_category extraits du chemin
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.migration.scanner import MigrationScanner


VIDEO_EXTS = frozenset({".mkv", ".mp4", ".avi"})


@pytest.fixture
def layout(tmp_path):
    """
    Arborescence test :

      tmp_path/
        Vidéos/Films/Action/         <-- source de migration (root du scan)
          matrix.mkv     -> OldNAS/matrix.mkv          (symlink valide)
          missing.mkv    -> OldNAS/missing.mkv         (symlink brisé)
          renamed.mkv    -> OldNAS/renamed.mkv         (brisé, dispo dans alt)
          physical.mkv                                 (fichier non-symlink)
          readme.txt                                   (extension non-vidéo)
          alreadyhere.mkv -> NewNAS/alreadyhere.mkv    (cible déjà sur dest)
        OldNAS/
          matrix.mkv  (1024 octets)
          (missing.mkv absent)
          (renamed.mkv absent)
        AltNAS/
          renamed.mkv  (200 octets)
        NewNAS/
          alreadyhere.mkv  (50 octets)
    """
    source_root = tmp_path / "Vidéos"
    old_nas = tmp_path / "OldNAS"
    alt_nas = tmp_path / "AltNAS"
    new_nas = tmp_path / "NewNAS"
    for d in (source_root, old_nas, alt_nas, new_nas):
        d.mkdir(parents=True, exist_ok=True)

    films_dir = source_root / "Films" / "Action"
    films_dir.mkdir(parents=True)

    # 1. Symlink valide
    (old_nas / "matrix.mkv").write_bytes(b"x" * 1024)
    (films_dir / "matrix.mkv").symlink_to(old_nas / "matrix.mkv")

    # 2. Symlink brisé sans alternative
    (films_dir / "missing.mkv").symlink_to(old_nas / "missing.mkv")

    # 3. Symlink brisé mais dispo dans alt_nas
    (alt_nas / "renamed.mkv").write_bytes(b"y" * 200)
    (films_dir / "renamed.mkv").symlink_to(old_nas / "renamed.mkv")

    # 4. Fichier physique (pas de symlink)
    (films_dir / "physical.mkv").write_bytes(b"z" * 512)

    # 5. Extension non-vidéo (skipped)
    (films_dir / "readme.txt").write_text("nope")

    # 6. Symlink dont la cible est déjà sur le nouveau NAS
    (new_nas / "alreadyhere.mkv").write_bytes(b"a" * 50)
    (films_dir / "alreadyhere.mkv").symlink_to(new_nas / "alreadyhere.mkv")

    return {
        "source": source_root,
        "old_nas": old_nas,
        "alt_nas": alt_nas,
        "new_nas": new_nas,
    }


def _by_name(cands):
    return {c.symlink_path.name: c for c in cands}


def test_scanner_yields_valid_symlink(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=layout["new_nas"]
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    c = cands["matrix.mkv"]
    assert c.is_broken is False
    assert c.is_symlink is True
    assert c.already_on_destination is False
    assert c.target_path == layout["old_nas"] / "matrix.mkv"
    assert c.size_bytes == 1024
    assert c.media_root == "Films"
    assert c.relative_category == "Action"


def test_scanner_marks_broken_when_no_alternative(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=layout["new_nas"]
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    c = cands["missing.mkv"]
    assert c.is_broken is True
    assert c.target_path is None


def test_scanner_uses_alternative_roots_to_recover_broken(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS,
        destination_root=layout["new_nas"],
        alternative_roots=[layout["alt_nas"]],
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    c = cands["renamed.mkv"]
    assert c.is_broken is False
    assert c.target_path == layout["alt_nas"] / "renamed.mkv"
    assert c.size_bytes == 200


def test_scanner_flags_already_on_destination(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=layout["new_nas"]
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    c = cands["alreadyhere.mkv"]
    assert c.already_on_destination is True
    assert c.is_broken is False


def test_scanner_skips_non_video_files(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=layout["new_nas"]
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    assert "readme.txt" not in cands


def test_scanner_includes_physical_files_with_is_symlink_false(layout):
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=layout["new_nas"]
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    c = cands["physical.mkv"]
    assert c.is_symlink is False
    assert c.is_broken is False
    assert c.target_path == c.symlink_path
    assert c.size_bytes == 512


def test_scanner_extracts_media_root_and_category(tmp_path):
    """Le 1er segment sous le root est le media_root, le reste = category."""
    src = tmp_path / "src"
    deep = src / "Séries" / "S" / "So-Sz" / "Sopranos (1999)"
    deep.mkdir(parents=True)
    target = tmp_path / "target.mkv"
    target.write_bytes(b"x")
    (deep / "ep1.mkv").symlink_to(target)

    scanner = MigrationScanner(video_extensions=VIDEO_EXTS, destination_root=tmp_path)
    cands = list(scanner.scan(src))
    assert len(cands) == 1
    assert cands[0].media_root == "Séries"
    assert cands[0].relative_category == "S/So-Sz/Sopranos (1999)"


def test_scanner_no_destination_root_no_already_on_destination_flag(layout):
    """Si destination_root est None, le scanner ne peut pas détecter
    'already on destination' et tous les symlinks valides restent normaux."""
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, destination_root=None
    )
    cands = _by_name(list(scanner.scan(layout["source"])))
    assert cands["alreadyhere.mkv"].already_on_destination is False


# ---- Filtrage par catégorie ----------------------------------------------


def test_scanner_filters_by_default_category_prefixes(tmp_path):
    """Par défaut, seuls Films/Séries/Animations sont scannés (Docs/Musique skip)."""
    src = tmp_path / "videotheque"
    (src / "Films" / "Drame").mkdir(parents=True)
    (src / "Séries" / "L").mkdir(parents=True)
    (src / "Animations" / "A").mkdir(parents=True)
    (src / "Docs").mkdir(parents=True)
    (src / "Musique").mkdir(parents=True)
    (src / "TV").mkdir(parents=True)

    (src / "Films" / "Drame" / "film.mkv").write_bytes(b"f")
    (src / "Séries" / "L" / "lost.mkv").write_bytes(b"l")
    (src / "Animations" / "A" / "anime.mkv").write_bytes(b"a")
    (src / "Docs" / "doc.mkv").write_bytes(b"d")
    (src / "Musique" / "clip.mkv").write_bytes(b"m")
    (src / "TV" / "show.mkv").write_bytes(b"t")

    scanner = MigrationScanner(video_extensions=VIDEO_EXTS)
    names = sorted(c.symlink_path.name for c in scanner.scan(src))
    assert names == ["anime.mkv", "film.mkv", "lost.mkv"]


def test_scanner_default_filter_handles_accents_and_case(tmp_path):
    """Match insensible aux accents + casse."""
    src = tmp_path / "src"
    (src / "Series" / "B").mkdir(parents=True)
    (src / "ANIME" / "naruto").mkdir(parents=True)
    (src / "FILMS").mkdir(parents=True)

    (src / "Series" / "B" / "bb.mkv").write_bytes(b"x")
    (src / "ANIME" / "naruto" / "ep1.mkv").write_bytes(b"x")
    (src / "FILMS" / "matrix.mkv").write_bytes(b"x")

    scanner = MigrationScanner(video_extensions=VIDEO_EXTS)
    names = sorted(c.symlink_path.name for c in scanner.scan(src))
    assert names == ["bb.mkv", "ep1.mkv", "matrix.mkv"]


def test_scanner_disable_category_filter_with_none(tmp_path):
    """category_prefixes=None désactive le filtrage (scan tout)."""
    src = tmp_path / "src"
    (src / "Docs").mkdir(parents=True)
    (src / "Musique").mkdir(parents=True)
    (src / "Docs" / "doc.mkv").write_bytes(b"x")
    (src / "Musique" / "clip.mkv").write_bytes(b"x")

    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, category_prefixes=None
    )
    names = sorted(c.symlink_path.name for c in scanner.scan(src))
    assert names == ["clip.mkv", "doc.mkv"]


def test_scanner_custom_category_prefixes(tmp_path):
    """Whitelist custom : on peut cibler 'Concerts' uniquement."""
    src = tmp_path / "src"
    (src / "Concerts").mkdir(parents=True)
    (src / "Films").mkdir(parents=True)
    (src / "Concerts" / "live.mkv").write_bytes(b"x")
    (src / "Films" / "matrix.mkv").write_bytes(b"x")

    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTS, category_prefixes=("concert",)
    )
    names = [c.symlink_path.name for c in scanner.scan(src)]
    assert names == ["live.mkv"]


def test_scanner_filter_walks_into_intermediate_dirs(tmp_path):
    """Le filtre accepte une catégorie à n'importe quelle profondeur (ex: Vidéothèque/Films)."""
    src = tmp_path / "wd10-1"
    deep = src / "Vidéothèque10" / "Films" / "Drame"
    deep.mkdir(parents=True)
    sibling = src / "Vidéothèque10" / "Docs"
    sibling.mkdir(parents=True)

    (deep / "film.mkv").write_bytes(b"x")
    (sibling / "doc.mkv").write_bytes(b"x")

    scanner = MigrationScanner(video_extensions=VIDEO_EXTS)
    names = [c.symlink_path.name for c in scanner.scan(src)]
    assert names == ["film.mkv"]
