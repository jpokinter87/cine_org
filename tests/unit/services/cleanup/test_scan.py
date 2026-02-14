"""Tests pour les fonctions d'analyse (scan) du CleanupService."""

from pathlib import Path
from unittest.mock import MagicMock

from src.core.entities.media import Movie
from src.core.entities.video import VideoFile
from src.services.cleanup import MisplacedSymlink


# ============================================================================
# Phase 3 : Analyse
# ============================================================================


class TestScanBrokenSymlinks:
    """Tests pour _scan_broken_symlinks."""

    def test_scan_broken_symlinks(self, cleanup_service, mock_repair_service, temp_dirs):
        """Detecte les symlinks casses via RepairService mocke."""
        video_dir = temp_dirs["video"]
        broken_link = video_dir / "Films" / "Action" / "broken.mkv"

        mock_repair_service.find_broken_symlinks.return_value = [broken_link]
        mock_repair_service.find_possible_targets.return_value = [
            (Path("/storage/Films/Action/film.mkv"), 95.0),
            (Path("/storage/Films/Action/autre.mkv"), 60.0),
        ]

        result = cleanup_service._scan_broken_symlinks(video_dir)

        assert len(result) == 1
        assert result[0].symlink_path == broken_link
        assert result[0].best_candidate == Path("/storage/Films/Action/film.mkv")
        assert result[0].candidate_score == 95.0


class TestScanEmptyDirs:
    """Tests pour _scan_empty_dirs."""

    def test_scan_empty_dirs(self, cleanup_service, temp_dirs):
        """Detecte les repertoires vides (bottom-up)."""
        video_dir = temp_dirs["video"]

        # Creer une arborescence avec des repertoires vides
        (video_dir / "Films" / "Action").mkdir(parents=True)
        (video_dir / "Films" / "Drame").mkdir(parents=True)
        # Action est vide, Drame est vide

        # Creer un fichier dans un autre repertoire pour qu'il ne soit pas vide
        (video_dir / "Films" / "Comedie").mkdir(parents=True)
        (video_dir / "Films" / "Comedie" / "film.mkv").symlink_to("/fake/target")

        result = cleanup_service._scan_empty_dirs(video_dir)

        # Action et Drame sont vides
        empty_paths = {p for p in result}
        assert video_dir / "Films" / "Action" in empty_paths
        assert video_dir / "Films" / "Drame" in empty_paths
        assert video_dir / "Films" / "Comedie" not in empty_paths

    def test_scan_empty_dirs_nested(self, cleanup_service, temp_dirs):
        """Detecte les repertoires imbriques vides."""
        video_dir = temp_dirs["video"]

        # Repertoire avec un seul sous-repertoire vide
        (video_dir / "Films" / "Action" / "A-M").mkdir(parents=True)
        # A-M est vide

        result = cleanup_service._scan_empty_dirs(video_dir)

        # A-M est vide
        empty_paths = {p for p in result}
        assert video_dir / "Films" / "Action" / "A-M" in empty_paths


class TestScanOversizedDirs:
    """Tests pour _scan_oversized_dirs (symlinks + repertoires, sauf episodes Series/)."""

    def test_scan_oversized_films_with_symlinks(self, cleanup_service, temp_dirs):
        """Detecte un repertoire Films/ avec trop de symlinks."""
        video_dir = temp_dirs["video"]
        genre_dir = video_dir / "Films" / "Action"
        genre_dir.mkdir(parents=True)

        # Creer 55 symlinks de films
        for i in range(55):
            link = genre_dir / f"Film {i:03d} (2020).mkv"
            link.symlink_to(f"/storage/film{i}.mkv")

        result = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=50)

        assert len(result) == 1
        assert result[0].parent_dir == genre_dir
        assert result[0].current_count == 55
        assert result[0].max_allowed == 50

    def test_scan_oversized_with_subdirs(self, cleanup_service, temp_dirs):
        """Detecte un repertoire avec trop de sous-repertoires."""
        video_dir = temp_dirs["video"]
        letter_dir = video_dir / "Séries" / "A"
        letter_dir.mkdir(parents=True)

        # Creer 55 sous-repertoires (ex: titres de series)
        for i in range(55):
            subdir = letter_dir / f"Anime {i:03d} (2020)"
            subdir.mkdir()

        result = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=50)

        assert len(result) == 1
        assert result[0].parent_dir == letter_dir

    def test_scan_oversized_series_anime_not_flagged(self, cleanup_service, temp_dirs):
        """Serie anime avec 200 episodes (symlinks) sans saisons -> pas de subdivision."""
        video_dir = temp_dirs["video"]
        anime_dir = video_dir / "Séries" / "N" / "Naruto (2002)"
        anime_dir.mkdir(parents=True)

        for i in range(200):
            link = anime_dir / f"Naruto (2002) - S01E{i+1:03d} - Episode {i+1}.mkv"
            link.symlink_to(f"/storage/naruto_ep{i}.mkv")

        result = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=50)

        assert len(result) == 0

    def test_scan_oversized_mixed_content_flagged(self, cleanup_service, temp_dirs):
        """Repertoire avec des symlinks ET sous-repertoires au-dela du seuil -> signale."""
        video_dir = temp_dirs["video"]
        genre_dir = video_dir / "Films" / "Action"
        genre_dir.mkdir(parents=True)

        # 30 symlinks + 25 sous-repertoires = 55 items
        for i in range(30):
            link = genre_dir / f"Film {i:03d} (2020).mkv"
            link.symlink_to(f"/storage/film{i}.mkv")
        for i in range(25):
            (genre_dir / f"Aa-{chr(65+i)}z").mkdir()

        result = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=50)

        assert len(result) == 1


class TestScanMisplacedSymlinks:
    """Tests pour _scan_misplaced_symlinks."""

    def test_scan_misplaced_symlink_wrong_genre(
        self, cleanup_service, mock_video_file_repo, mock_movie_repo,
        mock_organizer_service, temp_dirs,
    ):
        """Film dans le mauvais genre -> MisplacedSymlink."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer le symlink dans Drame
        drame_dir = video_dir / "Films" / "Drame"
        drame_dir.mkdir(parents=True)
        target = storage_dir / "Films" / "Action" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()
        symlink = drame_dir / "Film Action (2020).mkv"
        symlink.symlink_to(target)

        # Mock: le symlink est en BDD
        video_file = VideoFile(
            id="1",
            path=target,
            symlink_path=symlink,
            filename="Film Action (2020).mkv",
            size_bytes=1000,
        )
        mock_video_file_repo.get_by_symlink_path.return_value = video_file

        # Mock: le movie est trouve par file_path
        movie = Movie(
            id="1",
            title="Film Action",
            year=2020,
            genres=("Action",),
        )
        mock_movie_repo._session.exec.return_value.first.return_value = MagicMock(
            id=1, title="Film Action", year=2020, genres_json='["Action"]',
            tmdb_id=None, imdb_id=None, original_title=None,
            duration_seconds=None, overview=None, poster_path=None,
            vote_average=None, vote_count=None, imdb_rating=None, imdb_votes=None,
        )

        # Mock: le chemin attendu est dans Action
        expected_dir = video_dir / "Films" / "Action"
        mock_organizer_service.get_movie_video_destination.return_value = expected_dir

        result, not_in_db = cleanup_service._scan_misplaced_symlinks(video_dir)

        assert len(result) == 1
        assert result[0].symlink_path == symlink
        assert result[0].current_dir == drame_dir
        assert result[0].expected_dir == expected_dir

    def test_scan_misplaced_symlink_correct(
        self, cleanup_service, mock_video_file_repo, mock_movie_repo,
        mock_organizer_service, temp_dirs,
    ):
        """Film dans le bon genre -> pas de MisplacedSymlink."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer le symlink dans Action (correct)
        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)
        target = storage_dir / "Films" / "Action" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()
        symlink = action_dir / "Film Action (2020).mkv"
        symlink.symlink_to(target)

        # Mock: le symlink est en BDD
        video_file = VideoFile(
            id="1",
            path=target,
            symlink_path=symlink,
            filename="Film Action (2020).mkv",
            size_bytes=1000,
        )
        mock_video_file_repo.get_by_symlink_path.return_value = video_file

        # Mock: le movie est trouve par file_path
        mock_movie_repo._session.exec.return_value.first.return_value = MagicMock(
            id=1, title="Film Action", year=2020, genres_json='["Action"]',
            tmdb_id=None, imdb_id=None, original_title=None,
            duration_seconds=None, overview=None, poster_path=None,
            vote_average=None, vote_count=None, imdb_rating=None, imdb_votes=None,
        )

        # Mock: le chemin attendu est action_dir (le meme)
        mock_organizer_service.get_movie_video_destination.return_value = action_dir

        result, not_in_db = cleanup_service._scan_misplaced_symlinks(video_dir)

        assert len(result) == 0

    def test_scan_misplaced_symlink_not_in_db(
        self, cleanup_service, mock_video_file_repo, temp_dirs,
    ):
        """Symlink non reference en BDD -> incremente not_in_db_count."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer le symlink
        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)
        target = storage_dir / "Films" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()
        symlink = action_dir / "Film Inconnu (2020).mkv"
        symlink.symlink_to(target)

        # Mock: pas en BDD
        mock_video_file_repo.get_by_symlink_path.return_value = None
        mock_video_file_repo.get_by_path.return_value = None

        result, not_in_db = cleanup_service._scan_misplaced_symlinks(video_dir)

        assert len(result) == 0
        assert not_in_db == 1
