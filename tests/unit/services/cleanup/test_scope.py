"""Tests verifiant que le scan se limite aux sous-repertoires Films/ et Series/."""

from pathlib import Path


# ============================================================================
# Phase 7 : Scope restreint Films/Series
# ============================================================================


class TestScopeFilmsSeries:
    """Tests verifiant que le scan se limite aux sous-repertoires Films/ et Series/."""

    def test_scan_misplaced_ignores_outside_films_series(
        self, cleanup_service, mock_video_file_repo, temp_dirs,
    ):
        """Les symlinks hors Films/ et Series/ sont ignores par _scan_misplaced_symlinks."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer des sous-repertoires Films et hors-scope
        films_dir = video_dir / "Films" / "Action"
        films_dir.mkdir(parents=True)
        other_dir = video_dir / "Documentaires"
        other_dir.mkdir(parents=True)

        # Creer un fichier cible
        target = storage_dir / "film.mkv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

        # Symlink dans Films (dans le scope)
        symlink_in = films_dir / "Film (2020).mkv"
        symlink_in.symlink_to(target)

        # Symlink hors scope (Documentaires)
        symlink_out = other_dir / "Doc (2020).mkv"
        symlink_out.symlink_to(target)

        # Mock: pas en BDD (les deux seront comptees not_in_db si visitees)
        mock_video_file_repo.get_by_symlink_path.return_value = None
        mock_video_file_repo.get_by_path.return_value = None

        result, not_in_db = cleanup_service._scan_misplaced_symlinks(video_dir)

        # Seul le symlink dans Films/ doit etre visite -> 1 not_in_db
        assert not_in_db == 1

    def test_scan_oversized_ignores_outside_films_series(
        self, cleanup_service, temp_dirs,
    ):
        """Les repertoires hors Films/ et Series/ sont ignores par _scan_oversized_dirs."""
        video_dir = temp_dirs["video"]

        # Repertoire surcharge dans Films/ (dans le scope)
        genre_dir = video_dir / "Films" / "Action"
        genre_dir.mkdir(parents=True)
        for i in range(55):
            (genre_dir / f"Film {i:03d} (2020).mkv").symlink_to(f"/storage/f{i}.mkv")

        # Repertoire surcharge hors scope
        docs_dir = video_dir / "Documentaires"
        docs_dir.mkdir(parents=True)
        for i in range(55):
            (docs_dir / f"Doc {i:03d} (2020).mkv").symlink_to(f"/storage/d{i}.mkv")

        result = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=50)

        # Seul le repertoire dans Films/ doit etre detecte
        assert len(result) == 1
        assert result[0].parent_dir == genre_dir

    def test_scan_empty_dirs_ignores_outside_films_series(
        self, cleanup_service, temp_dirs,
    ):
        """Les repertoires vides hors Films/ et Series/ sont ignores."""
        video_dir = temp_dirs["video"]

        # Repertoire vide dans Films/ (dans le scope)
        (video_dir / "Films" / "Action").mkdir(parents=True)

        # Repertoire vide hors scope
        (video_dir / "Documentaires" / "Nature").mkdir(parents=True)

        result = cleanup_service._scan_empty_dirs(video_dir)

        result_paths = {p for p in result}
        assert video_dir / "Films" / "Action" in result_paths
        assert video_dir / "Documentaires" / "Nature" not in result_paths

    def test_scan_broken_symlinks_ignores_outside_films_series(
        self, cleanup_service, mock_repair_service, temp_dirs,
    ):
        """Les symlinks casses hors Films/ et Series/ sont filtres."""
        video_dir = temp_dirs["video"]

        # Symlink casse dans Films/ (dans le scope)
        broken_in = video_dir / "Films" / "Action" / "broken.mkv"
        # Symlink casse hors scope
        broken_out = video_dir / "Documentaires" / "broken_doc.mkv"

        mock_repair_service.find_broken_symlinks.return_value = [
            broken_in, broken_out,
        ]
        mock_repair_service.find_possible_targets.return_value = []

        result = cleanup_service._scan_broken_symlinks(video_dir)

        # Seul le symlink dans Films/ doit etre retourne
        assert len(result) == 1
        assert result[0].symlink_path == broken_in

    def test_scan_includes_series_subdir(
        self, cleanup_service, temp_dirs,
    ):
        """Les repertoires dans Series/ sont dans le scope."""
        video_dir = temp_dirs["video"]

        # Repertoire vide dans Series/
        (video_dir / "Séries" / "B" / "Breaking Bad (2008)" / "Saison 01").mkdir(parents=True)

        result = cleanup_service._scan_empty_dirs(video_dir)

        result_paths = {p for p in result}
        assert video_dir / "Séries" / "B" / "Breaking Bad (2008)" / "Saison 01" in result_paths
