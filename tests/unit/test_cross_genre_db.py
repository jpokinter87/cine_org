"""Tests pour la detection cross-genre via requete DB (symlink_path)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.cleanup.analyzers import (
    scan_cross_genre_duplicates,
    _scan_cross_genre_via_db,
)
from src.services.cleanup.dataclasses import CrossGenreDuplicate


class TestScanCrossGenreViaDB:
    """Tests pour la detection cross-genre via DB."""

    def test_two_genres_detected_via_db(self, tmp_path: Path):
        """Deux symlink_path dans des genres differents pour le meme file_path."""
        video_dir = tmp_path / "video"
        file_path = "/storage/Films/Action/Film.mkv"
        sl_action = str(video_dir / "Films" / "Action & Aventure" / "Film.mkv")
        sl_drame = str(video_dir / "Films" / "Drame" / "Film.mkv")

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {
            file_path: [(1, sl_action), (2, sl_drame)],
        }

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 1
        dup = result[0]
        assert dup.target_path == Path(file_path)
        assert len(dup.remove) == 1
        assert dup.keep_genre != ""
        assert dup.remove_genres[0] != dup.keep_genre

    def test_priority_genre_kept_via_db(self, tmp_path: Path):
        """Le genre prioritaire (Animation > Drame) est conserve."""
        video_dir = tmp_path / "video"
        sl_anim = str(video_dir / "Films" / "Animation" / "A-G" / "Film.mkv")
        sl_drame = str(video_dir / "Films" / "Drame" / "Film.mkv")
        file_path = "/storage/Films/Film.mkv"

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {
            file_path: [(1, sl_anim), (2, sl_drame)],
        }

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 1
        dup = result[0]
        assert dup.keep_genre == "Animation"
        assert dup.keep == Path(sl_anim)
        assert Path(sl_drame) in dup.remove
        assert "Drame" in dup.remove_genres

    def test_three_genres_via_db(self, tmp_path: Path):
        """Trois symlink_path dans des genres differents."""
        video_dir = tmp_path / "video"
        sl_sf = str(video_dir / "Films" / "SF" / "Film.mkv")
        sl_horreur = str(video_dir / "Films" / "Horreur" / "Film.mkv")
        sl_drame = str(video_dir / "Films" / "Drame" / "Film.mkv")
        file_path = "/storage/Films/Film.mkv"

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {
            file_path: [(1, sl_sf), (2, sl_horreur), (3, sl_drame)],
        }

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 1
        dup = result[0]
        assert dup.keep == Path(sl_sf)
        assert dup.keep_genre == "SF"
        assert len(dup.remove) == 2

    def test_same_genre_ignored_via_db(self, tmp_path: Path):
        """Deux symlink_path dans le meme genre ne sont pas cross-genre."""
        video_dir = tmp_path / "video"
        sl1 = str(video_dir / "Films" / "Drame" / "Film_v1.mkv")
        sl2 = str(video_dir / "Films" / "Drame" / "Film_v2.mkv")
        file_path = "/storage/Films/Film.mkv"

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {
            file_path: [(1, sl1), (2, sl2)],
        }

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 0

    def test_empty_db_returns_empty(self, tmp_path: Path):
        """Pas de candidats en DB retourne une liste vide."""
        video_dir = tmp_path / "video"

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {}

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 0

    def test_multiple_file_paths_via_db(self, tmp_path: Path):
        """Plusieurs file_path avec doublons cross-genre chacun."""
        video_dir = tmp_path / "video"
        fp1 = "/storage/Films/Film1.mkv"
        fp2 = "/storage/Films/Film2.mkv"

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {
            fp1: [
                (1, str(video_dir / "Films" / "Action & Aventure" / "Film1.mkv")),
                (2, str(video_dir / "Films" / "Drame" / "Film1.mkv")),
            ],
            fp2: [
                (3, str(video_dir / "Films" / "Horreur" / "Film2.mkv")),
                (4, str(video_dir / "Films" / "Comédie" / "Film2.mkv")),
            ],
        }

        result = _scan_cross_genre_via_db(video_dir, movie_repo)

        assert len(result) == 2


class TestScanCrossGenreFallback:
    """Tests pour le fallback filesystem quand movie_repo absent ou vide."""

    def test_no_repo_uses_filesystem(self, tmp_path: Path):
        """Sans movie_repo, le scan filesystem est utilise."""
        # Creer des fichiers pour le scan filesystem
        storage = tmp_path / "storage"
        storage.mkdir()
        target = storage / "film.mkv"
        target.write_text("fake video")

        films_dir = tmp_path / "Films"
        for genre in ("Action & Aventure", "Drame"):
            genre_dir = films_dir / genre
            genre_dir.mkdir(parents=True)
            (genre_dir / "Film.mkv").symlink_to(target)

        result = scan_cross_genre_duplicates(tmp_path)

        assert len(result) == 1

    def test_db_empty_falls_back_to_filesystem(self, tmp_path: Path):
        """Si la DB ne retourne rien, fallback filesystem."""
        storage = tmp_path / "storage"
        storage.mkdir()
        target = storage / "film.mkv"
        target.write_text("fake video")

        films_dir = tmp_path / "Films"
        for genre in ("Action & Aventure", "Drame"):
            genre_dir = films_dir / genre
            genre_dir.mkdir(parents=True)
            (genre_dir / "Film.mkv").symlink_to(target)

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.return_value = {}

        result = scan_cross_genre_duplicates(tmp_path, movie_repo=movie_repo)

        assert len(result) == 1

    def test_db_exception_falls_back_to_filesystem(self, tmp_path: Path):
        """En cas d'erreur DB, fallback filesystem."""
        storage = tmp_path / "storage"
        storage.mkdir()
        target = storage / "film.mkv"
        target.write_text("fake video")

        films_dir = tmp_path / "Films"
        for genre in ("Action & Aventure", "Drame"):
            genre_dir = films_dir / genre
            genre_dir.mkdir(parents=True)
            (genre_dir / "Film.mkv").symlink_to(target)

        movie_repo = MagicMock()
        movie_repo.get_cross_genre_candidates.side_effect = Exception("DB error")

        result = scan_cross_genre_duplicates(tmp_path, movie_repo=movie_repo)

        assert len(result) == 1
