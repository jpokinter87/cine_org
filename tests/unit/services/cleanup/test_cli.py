"""Tests pour la commande CLI cleanup."""

from pathlib import Path

from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupReport,
    CleanupResult,
)


# ============================================================================
# Phase 6 : CLI
# ============================================================================


class TestCleanupCLI:
    """Tests pour la commande CLI cleanup."""

    def test_cleanup_dry_run_shows_report(self, tmp_path):
        """En mode dry-run, pas de modification."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        # Mock le container et ses dependances
        with patch("src.adapters.cli.commands.cleanup_command.Container") as MockContainer:
            mock_container = MagicMock()
            MockContainer.return_value = mock_container

            mock_config = MagicMock()
            mock_config.video_dir = str(tmp_path / "video")
            mock_config.storage_dir = str(tmp_path / "storage")
            mock_container.config.return_value = mock_config

            # Creer les repertoires
            (tmp_path / "video").mkdir(exist_ok=True)
            (tmp_path / "storage").mkdir(exist_ok=True)

            mock_cleanup_svc = MagicMock()
            mock_cleanup_svc.analyze.return_value = CleanupReport(
                video_dir=tmp_path / "video",
                broken_symlinks=[],
                misplaced_symlinks=[],
                oversized_dirs=[],
                empty_dirs=[],
            )
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup"])

            # Pas d'appel aux methodes de correction
            mock_cleanup_svc.repair_broken_symlinks.assert_not_called()
            mock_cleanup_svc.fix_misplaced_symlinks.assert_not_called()
            mock_cleanup_svc.subdivide_oversized_dirs.assert_not_called()
            mock_cleanup_svc.clean_empty_dirs.assert_not_called()

    def test_cleanup_fix_executes(self, tmp_path):
        """Avec --fix, appelle les methodes d'execution."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        with patch("src.adapters.cli.commands.cleanup_command.Container") as MockContainer:
            mock_container = MagicMock()
            MockContainer.return_value = mock_container

            mock_config = MagicMock()
            mock_config.video_dir = str(tmp_path / "video")
            mock_config.storage_dir = str(tmp_path / "storage")
            mock_container.config.return_value = mock_config

            (tmp_path / "video").mkdir(exist_ok=True)
            (tmp_path / "storage").mkdir(exist_ok=True)

            broken = [
                BrokenSymlinkInfo(
                    symlink_path=Path("/video/film.mkv"),
                    original_target=Path("/storage/old.mkv"),
                    best_candidate=Path("/storage/new.mkv"),
                    candidate_score=95.0,
                ),
                BrokenSymlinkInfo(
                    symlink_path=Path("/video/film2.mkv"),
                    original_target=Path("/storage/old2.mkv"),
                    best_candidate=None,
                    candidate_score=0.0,
                ),
            ]
            empty = [tmp_path / "video" / "empty"]

            mock_cleanup_svc = MagicMock()
            mock_cleanup_svc.analyze.return_value = CleanupReport(
                video_dir=tmp_path / "video",
                broken_symlinks=broken,
                misplaced_symlinks=[],
                oversized_dirs=[],
                empty_dirs=empty,
            )
            mock_cleanup_svc.repair_broken_symlinks.return_value = CleanupResult(
                repaired_symlinks=1,
            )
            mock_cleanup_svc.delete_broken_symlinks.return_value = CleanupResult(
                broken_symlinks_deleted=1,
            )
            mock_cleanup_svc.fix_misplaced_symlinks.return_value = CleanupResult()
            mock_cleanup_svc.subdivide_oversized_dirs.return_value = CleanupResult()
            mock_cleanup_svc.clean_empty_dirs.return_value = CleanupResult(
                empty_dirs_removed=1,
            )
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup", "--fix"])

            mock_cleanup_svc.repair_broken_symlinks.assert_called_once()
            # delete_broken_symlinks appele pour l'irreparable (score=0, pas de candidat)
            mock_cleanup_svc.delete_broken_symlinks.assert_called_once()
            # Verifie que seul l'irreparable est passe a delete
            deleted_list = mock_cleanup_svc.delete_broken_symlinks.call_args[0][0]
            assert len(deleted_list) == 1
            assert deleted_list[0].symlink_path == Path("/video/film2.mkv")
            mock_cleanup_svc.clean_empty_dirs.assert_called_once()


# ============================================================================
# Phase 8b : CLI + Cache
# ============================================================================


class TestCleanupCLICache:
    """Tests pour l'utilisation du cache dans la commande CLI."""

    def test_cleanup_dry_run_saves_cache(self, tmp_path):
        """En mode dry-run, le rapport est sauvegarde dans le cache."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        with patch("src.adapters.cli.commands.cleanup_command.Container") as MockContainer, \
             patch("src.adapters.cli.commands.cleanup_command.save_report_cache") as mock_save:
            mock_container = MagicMock()
            MockContainer.return_value = mock_container

            mock_config = MagicMock()
            mock_config.video_dir = str(tmp_path / "video")
            mock_config.storage_dir = str(tmp_path / "storage")
            mock_container.config.return_value = mock_config

            (tmp_path / "video").mkdir(exist_ok=True)
            (tmp_path / "storage").mkdir(exist_ok=True)

            report = CleanupReport(
                video_dir=tmp_path / "video",
                broken_symlinks=[],
                misplaced_symlinks=[],
                oversized_dirs=[],
                empty_dirs=[],
            )
            mock_cleanup_svc = MagicMock()
            mock_cleanup_svc.analyze.return_value = report
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup"])

            mock_save.assert_called_once_with(report)

    def test_cleanup_fix_uses_cache(self, tmp_path):
        """Avec --fix, utilise le cache si disponible et recent."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        cached_report = CleanupReport(
            video_dir=tmp_path / "video",
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[Path(tmp_path / "video" / "Films" / "Vide")],
        )

        with patch("src.adapters.cli.commands.cleanup_command.Container") as MockContainer, \
             patch("src.adapters.cli.commands.cleanup_command.load_report_cache") as mock_load, \
             patch("src.adapters.cli.commands.cleanup_command.save_report_cache"):
            mock_load.return_value = cached_report

            mock_container = MagicMock()
            MockContainer.return_value = mock_container

            mock_config = MagicMock()
            mock_config.video_dir = str(tmp_path / "video")
            mock_config.storage_dir = str(tmp_path / "storage")
            mock_container.config.return_value = mock_config

            (tmp_path / "video").mkdir(exist_ok=True)
            (tmp_path / "storage").mkdir(exist_ok=True)

            mock_cleanup_svc = MagicMock()
            mock_cleanup_svc.clean_empty_dirs.return_value = CleanupResult(
                empty_dirs_removed=1,
            )
            mock_cleanup_svc.repair_broken_symlinks.return_value = CleanupResult()
            mock_cleanup_svc.fix_misplaced_symlinks.return_value = CleanupResult()
            mock_cleanup_svc.subdivide_oversized_dirs.return_value = CleanupResult()
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup", "--fix"])

            # Le cache est utilise, analyze() n'est PAS appele
            mock_cleanup_svc.analyze.assert_not_called()
            mock_cleanup_svc.clean_empty_dirs.assert_called_once()

    def test_cleanup_fix_no_cache_runs_analysis(self, tmp_path):
        """Avec --fix sans cache, lance l'analyse normalement."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        with patch("src.adapters.cli.commands.cleanup_command.Container") as MockContainer, \
             patch("src.adapters.cli.commands.cleanup_command.load_report_cache") as mock_load, \
             patch("src.adapters.cli.commands.cleanup_command.save_report_cache"):
            mock_load.return_value = None  # Pas de cache

            mock_container = MagicMock()
            MockContainer.return_value = mock_container

            mock_config = MagicMock()
            mock_config.video_dir = str(tmp_path / "video")
            mock_config.storage_dir = str(tmp_path / "storage")
            mock_container.config.return_value = mock_config

            (tmp_path / "video").mkdir(exist_ok=True)
            (tmp_path / "storage").mkdir(exist_ok=True)

            report = CleanupReport(
                video_dir=tmp_path / "video",
                broken_symlinks=[],
                misplaced_symlinks=[],
                oversized_dirs=[],
                empty_dirs=[],
            )
            mock_cleanup_svc = MagicMock()
            mock_cleanup_svc.analyze.return_value = report
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup", "--fix"])

            # Pas de cache -> analyze() est appele
            mock_cleanup_svc.analyze.assert_called_once()
