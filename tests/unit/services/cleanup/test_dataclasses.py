"""Tests pour les dataclasses du module cleanup."""

from pathlib import Path

from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupReport,
    MisplacedSymlink,
    SubdivisionPlan,
)


# ============================================================================
# Phase 1 : Dataclasses
# ============================================================================


class TestCleanupDataclasses:
    """Tests pour les dataclasses du module cleanup."""

    def test_cleanup_report_empty(self):
        """Rapport vide, has_issues=False, total_issues=0."""
        report = CleanupReport(
            video_dir=Path("/video"),
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
        )
        assert report.has_issues is False
        assert report.total_issues == 0

    def test_cleanup_report_with_issues(self):
        """Rapport avec problemes, compteurs corrects."""
        broken = [
            BrokenSymlinkInfo(
                symlink_path=Path("/video/Films/lien.mkv"),
                original_target=Path("/storage/film.mkv"),
            )
        ]
        misplaced = [
            MisplacedSymlink(
                symlink_path=Path("/video/Films/Drame/film.mkv"),
                target_path=Path("/storage/film.mkv"),
                current_dir=Path("/video/Films/Drame"),
                expected_dir=Path("/video/Films/Action"),
            )
        ]
        empty = [Path("/video/Films/Vide")]

        report = CleanupReport(
            video_dir=Path("/video"),
            broken_symlinks=broken,
            misplaced_symlinks=misplaced,
            oversized_dirs=[],
            empty_dirs=empty,
        )
        assert report.has_issues is True
        assert report.total_issues == 3  # 1 broken + 1 misplaced + 1 empty

    def test_subdivision_plan_creation(self):
        """SubdivisionPlan avec ranges et items_to_move."""
        plan = SubdivisionPlan(
            parent_dir=Path("/video/Films/Action"),
            current_count=60,
            max_allowed=50,
            ranges=[("Aa", "Am"), ("An", "Az")],
            items_to_move=[
                (Path("/video/Films/Action/Alpha.mkv"), Path("/video/Films/Action/Aa-Am/Alpha.mkv")),
                (Path("/video/Films/Action/Zeta.mkv"), Path("/video/Films/Action/An-Az/Zeta.mkv")),
            ],
        )
        assert plan.current_count == 60
        assert plan.max_allowed == 50
        assert len(plan.ranges) == 2
        assert len(plan.items_to_move) == 2
