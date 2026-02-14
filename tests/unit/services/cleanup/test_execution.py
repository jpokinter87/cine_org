"""Tests pour les methodes d'execution du CleanupService."""

from pathlib import Path

from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupResult,
    MisplacedSymlink,
)


# ============================================================================
# Phase 4 : Execution
# ============================================================================


class TestRepairBrokenSymlinks:
    """Tests pour repair_broken_symlinks."""

    def test_repair_broken_symlinks_high_score(
        self, cleanup_service, mock_repair_service,
    ):
        """Repare si score >= 90."""
        broken = [
            BrokenSymlinkInfo(
                symlink_path=Path("/video/Films/film.mkv"),
                original_target=Path("/storage/old.mkv"),
                best_candidate=Path("/storage/new.mkv"),
                candidate_score=95.0,
            ),
        ]

        result = cleanup_service.repair_broken_symlinks(broken, min_score=90.0)

        assert result.repaired_symlinks == 1
        assert result.failed_repairs == 0
        mock_repair_service.repair_symlink.assert_called_once_with(
            Path("/video/Films/film.mkv"), Path("/storage/new.mkv")
        )

    def test_repair_broken_symlinks_low_score(
        self, cleanup_service, mock_repair_service,
    ):
        """Ne repare pas si score < 90."""
        broken = [
            BrokenSymlinkInfo(
                symlink_path=Path("/video/Films/film.mkv"),
                original_target=Path("/storage/old.mkv"),
                best_candidate=Path("/storage/new.mkv"),
                candidate_score=75.0,
            ),
        ]

        result = cleanup_service.repair_broken_symlinks(broken, min_score=90.0)

        assert result.repaired_symlinks == 0
        mock_repair_service.repair_symlink.assert_not_called()


class TestDeleteBrokenSymlinks:
    """Tests pour delete_broken_symlinks (suppression des symlinks irreparables)."""

    def test_delete_broken_symlinks(self, cleanup_service, tmp_path):
        """Supprime les symlinks casses irrecuperables."""
        action_dir = tmp_path / "video" / "Films" / "Action"
        action_dir.mkdir(parents=True)

        # Creer des symlinks casses
        broken1 = action_dir / "film_sans_candidat.mkv"
        broken1.symlink_to("/storage/inexistant1.mkv")
        broken2 = action_dir / "film_score_faible.mkv"
        broken2.symlink_to("/storage/inexistant2.mkv")

        broken_list = [
            BrokenSymlinkInfo(
                symlink_path=broken1,
                original_target=Path("/storage/inexistant1.mkv"),
                best_candidate=None,
                candidate_score=0.0,
            ),
            BrokenSymlinkInfo(
                symlink_path=broken2,
                original_target=Path("/storage/inexistant2.mkv"),
                best_candidate=Path("/storage/maybe.mkv"),
                candidate_score=45.0,
            ),
        ]

        result = cleanup_service.delete_broken_symlinks(broken_list)

        assert result.broken_symlinks_deleted == 2
        assert not broken1.exists() and not broken1.is_symlink()
        assert not broken2.exists() and not broken2.is_symlink()

    def test_delete_broken_symlinks_already_gone(self, cleanup_service, tmp_path):
        """Gere gracieusement un symlink deja supprime."""
        ghost = tmp_path / "video" / "Films" / "ghost.mkv"

        broken_list = [
            BrokenSymlinkInfo(
                symlink_path=ghost,
                original_target=Path("/storage/old.mkv"),
            ),
        ]

        result = cleanup_service.delete_broken_symlinks(broken_list)

        assert result.broken_symlinks_deleted == 0
        assert len(result.errors) == 1

    def test_cleanup_result_broken_symlinks_deleted_default(self):
        """CleanupResult a broken_symlinks_deleted=0 par defaut."""
        result = CleanupResult()
        assert result.broken_symlinks_deleted == 0


class TestFixMisplacedSymlinks:
    """Tests pour fix_misplaced_symlinks."""

    def test_fix_misplaced_moves_symlink(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Deplace le symlink et met a jour la BDD."""
        # Creer le symlink physiquement
        current_dir = tmp_path / "video" / "Films" / "Drame"
        expected_dir = tmp_path / "video" / "Films" / "Action"
        current_dir.mkdir(parents=True)
        expected_dir.mkdir(parents=True)

        target = tmp_path / "storage" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        symlink = current_dir / "Film Action (2020).mkv"
        symlink.symlink_to(target)

        misplaced = [
            MisplacedSymlink(
                symlink_path=symlink,
                target_path=target,
                current_dir=current_dir,
                expected_dir=expected_dir,
            ),
        ]

        result = cleanup_service.fix_misplaced_symlinks(misplaced)

        assert result.moved_symlinks == 1
        new_path = expected_dir / "Film Action (2020).mkv"
        assert new_path.is_symlink()
        assert not symlink.exists()
        mock_video_file_repo.update_symlink_path.assert_called_once_with(
            symlink, new_path,
        )


class TestCleanEmptyDirs:
    """Tests pour clean_empty_dirs."""

    def test_clean_empty_dirs(self, cleanup_service, tmp_path):
        """Supprime les repertoires vides."""
        empty1 = tmp_path / "video" / "Films" / "Action"
        empty2 = tmp_path / "video" / "Films" / "Drame"
        empty1.mkdir(parents=True)
        empty2.mkdir(parents=True)

        result = cleanup_service.clean_empty_dirs([empty1, empty2])

        assert result.empty_dirs_removed == 2
        assert not empty1.exists()
        assert not empty2.exists()
