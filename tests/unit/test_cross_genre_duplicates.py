"""Tests pour la detection et correction des doublons symlinks cross-genre."""

import os
from pathlib import Path

import pytest

from src.services.cleanup.analyzers import scan_cross_genre_duplicates
from src.services.cleanup.dataclasses import CrossGenreDuplicate
from src.services.cleanup.executors import fix_cross_genre_duplicates


def _create_symlink(tmp_path: Path, genre: str, filename: str, target: Path) -> Path:
    """Cree un symlink dans video/Films/{genre}/{filename} pointant vers target."""
    genre_dir = tmp_path / "Films" / genre
    genre_dir.mkdir(parents=True, exist_ok=True)
    symlink = genre_dir / filename
    symlink.symlink_to(target)
    return symlink


def _create_target_file(tmp_path: Path, name: str = "movie.mkv") -> Path:
    """Cree un fichier physique dans storage/."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    target = storage / name
    target.write_text("fake video")
    return target


class TestScanCrossGenreDuplicates:
    """Tests pour scan_cross_genre_duplicates."""

    def test_two_genres_same_target(self, tmp_path: Path):
        """Deux symlinks vers le meme fichier dans deux genres differents."""
        target = _create_target_file(tmp_path)
        sl_action = _create_symlink(tmp_path, "Action & Aventure", "Film.mkv", target)
        sl_drame = _create_symlink(tmp_path, "Drame", "Film.mkv", target)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 1
        dup = result[0]
        assert dup.target_path == target.resolve()
        assert dup.keep in (sl_action, sl_drame)
        assert len(dup.remove) == 1

    def test_priority_genre_kept(self, tmp_path: Path):
        """Le genre le plus prioritaire dans GENRE_HIERARCHY est conserve."""
        target = _create_target_file(tmp_path)
        # Animation est plus prioritaire que Drame dans GENRE_HIERARCHY
        sl_anim = _create_symlink(tmp_path, "Animation", "Film.mkv", target)
        sl_drame = _create_symlink(tmp_path, "Drame", "Film.mkv", target)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 1
        dup = result[0]
        assert dup.keep == sl_anim
        assert dup.keep_genre == "Animation"
        assert sl_drame in dup.remove
        assert "Drame" in dup.remove_genres

    def test_three_genres_keep_most_priority(self, tmp_path: Path):
        """Avec 3 genres, garde le plus prioritaire et supprime les 2 autres."""
        target = _create_target_file(tmp_path)
        # SF > Horreur > Drame dans GENRE_HIERARCHY
        sl_sf = _create_symlink(tmp_path, "SF", "Film.mkv", target)
        sl_horreur = _create_symlink(tmp_path, "Horreur", "Film.mkv", target)
        sl_drame = _create_symlink(tmp_path, "Drame", "Film.mkv", target)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 1
        dup = result[0]
        assert dup.keep == sl_sf
        assert dup.keep_genre == "SF"
        assert len(dup.remove) == 2
        assert sl_horreur in dup.remove
        assert sl_drame in dup.remove

    def test_no_duplicates(self, tmp_path: Path):
        """Pas de doublons : chaque symlink pointe vers un fichier different."""
        target1 = _create_target_file(tmp_path, "film1.mkv")
        target2 = _create_target_file(tmp_path, "film2.mkv")
        _create_symlink(tmp_path, "Action & Aventure", "Film1.mkv", target1)
        _create_symlink(tmp_path, "Drame", "Film2.mkv", target2)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 0

    def test_same_genre_ignored(self, tmp_path: Path):
        """Deux symlinks dans le meme genre ne sont pas des cross-genre."""
        target = _create_target_file(tmp_path)
        _create_symlink(tmp_path, "Drame", "Film_v1.mkv", target)
        _create_symlink(tmp_path, "Drame", "Film_v2.mkv", target)

        result = scan_cross_genre_duplicates(tmp_path)

        # Pas de cross-genre (meme genre = traite par scan_duplicate_symlinks)
        assert len(result) == 0

    def test_broken_symlink_ignored(self, tmp_path: Path):
        """Les symlinks casses sont ignores."""
        target = _create_target_file(tmp_path)
        _create_symlink(tmp_path, "Action & Aventure", "Film.mkv", target)
        # Creer un symlink casse
        broken_dir = tmp_path / "Films" / "Drame"
        broken_dir.mkdir(parents=True, exist_ok=True)
        broken_sl = broken_dir / "Film.mkv"
        broken_sl.symlink_to(tmp_path / "nonexistent.mkv")

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 0

    def test_no_films_dir(self, tmp_path: Path):
        """Pas de repertoire Films/ : liste vide."""
        result = scan_cross_genre_duplicates(tmp_path)
        assert len(result) == 0

    def test_subdirectories_within_genre(self, tmp_path: Path):
        """Symlinks dans des sous-repertoires de genre (subdivisions alphabetiques)."""
        target = _create_target_file(tmp_path)
        # Subdivision alphabetique : Animation/A-G/Film.mkv
        sub_dir = tmp_path / "Films" / "Animation" / "A-G"
        sub_dir.mkdir(parents=True, exist_ok=True)
        sl_anim = sub_dir / "Film.mkv"
        sl_anim.symlink_to(target)
        sl_drame = _create_symlink(tmp_path, "Drame", "Film.mkv", target)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 1
        dup = result[0]
        assert dup.keep == sl_anim
        assert dup.keep_genre == "Animation"
        assert sl_drame in dup.remove


class TestFixCrossGenreDuplicates:
    """Tests pour fix_cross_genre_duplicates."""

    def test_removes_redundant_symlinks(self, tmp_path: Path):
        """Les symlinks redondants sont supprimes, le keep reste."""
        target = _create_target_file(tmp_path)
        sl_keep = _create_symlink(tmp_path, "Animation", "Film.mkv", target)
        sl_remove = _create_symlink(tmp_path, "Drame", "Film.mkv", target)

        dup = CrossGenreDuplicate(
            target_path=target,
            keep=sl_keep,
            keep_genre="Animation",
            remove=[sl_remove],
            remove_genres=["Drame"],
        )

        result = fix_cross_genre_duplicates([dup])

        assert result.cross_genre_removed == 1
        assert sl_keep.exists()
        assert not sl_remove.exists()
        assert len(result.errors) == 0

    def test_already_removed(self, tmp_path: Path):
        """Symlink deja supprime : pas d'erreur fatale."""
        target = _create_target_file(tmp_path)
        sl_keep = _create_symlink(tmp_path, "Animation", "Film.mkv", target)
        # Chemin qui n'existe pas
        sl_gone = tmp_path / "Films" / "Drame" / "Film.mkv"

        dup = CrossGenreDuplicate(
            target_path=target,
            keep=sl_keep,
            keep_genre="Animation",
            remove=[sl_gone],
            remove_genres=["Drame"],
        )

        result = fix_cross_genre_duplicates([dup])

        assert result.cross_genre_removed == 0
        assert len(result.errors) == 1
        assert "deja absent" in result.errors[0]

    def test_multiple_groups(self, tmp_path: Path):
        """Correction de plusieurs groupes cross-genre."""
        target1 = _create_target_file(tmp_path, "film1.mkv")
        target2 = _create_target_file(tmp_path, "film2.mkv")

        sl_keep1 = _create_symlink(tmp_path, "Horreur", "Film1.mkv", target1)
        sl_rm1 = _create_symlink(tmp_path, "Drame", "Film1.mkv", target1)
        sl_keep2 = _create_symlink(tmp_path, "Animation", "Film2.mkv", target2)
        sl_rm2 = _create_symlink(tmp_path, "Comédie", "Film2.mkv", target2)

        dups = [
            CrossGenreDuplicate(
                target_path=target1,
                keep=sl_keep1,
                keep_genre="Horreur",
                remove=[sl_rm1],
                remove_genres=["Drame"],
            ),
            CrossGenreDuplicate(
                target_path=target2,
                keep=sl_keep2,
                keep_genre="Animation",
                remove=[sl_rm2],
                remove_genres=["Comédie"],
            ),
        ]

        result = fix_cross_genre_duplicates(dups)

        assert result.cross_genre_removed == 2
        assert sl_keep1.exists()
        assert sl_keep2.exists()
        assert not sl_rm1.exists()
        assert not sl_rm2.exists()
