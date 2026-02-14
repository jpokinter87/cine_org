"""Tests pour la serialisation/deserialisation du cache CleanupReport."""

import os
from pathlib import Path

from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupReport,
    MisplacedSymlink,
    SubdivisionPlan,
)


# ============================================================================
# Phase 8 : Cache du rapport d'analyse
# ============================================================================


class TestReportCache:
    """Tests pour la serialisation/deserialisation du cache CleanupReport."""

    def test_save_and_load_report_cache(self, tmp_path):
        """Sauvegarde et rechargement d'un rapport complet."""
        from src.services.cleanup import save_report_cache, load_report_cache

        video_dir = tmp_path / "video"
        cache_dir = tmp_path / "cache"

        report = CleanupReport(
            video_dir=video_dir,
            broken_symlinks=[
                BrokenSymlinkInfo(
                    symlink_path=Path("/video/Films/broken.mkv"),
                    original_target=Path("/storage/old.mkv"),
                    best_candidate=Path("/storage/new.mkv"),
                    candidate_score=95.0,
                ),
            ],
            misplaced_symlinks=[
                MisplacedSymlink(
                    symlink_path=Path("/video/Films/Drame/film.mkv"),
                    target_path=Path("/storage/film.mkv"),
                    current_dir=Path("/video/Films/Drame"),
                    expected_dir=Path("/video/Films/Action"),
                    media_title="Film Action",
                ),
            ],
            oversized_dirs=[
                SubdivisionPlan(
                    parent_dir=Path("/video/Films/Action"),
                    current_count=60,
                    max_allowed=50,
                    ranges=[("Aa", "Am"), ("An", "Az")],
                    items_to_move=[
                        (Path("/video/Films/Action/Alpha.mkv"), Path("/video/Films/Action/Aa-Am/Alpha.mkv")),
                    ],
                ),
            ],
            empty_dirs=[Path("/video/Films/Vide")],
            not_in_db_count=5,
        )

        save_report_cache(report, cache_dir=cache_dir)
        loaded = load_report_cache(video_dir, cache_dir=cache_dir)

        assert loaded is not None
        assert loaded.video_dir == video_dir
        assert len(loaded.broken_symlinks) == 1
        assert loaded.broken_symlinks[0].symlink_path == Path("/video/Films/broken.mkv")
        assert loaded.broken_symlinks[0].best_candidate == Path("/storage/new.mkv")
        assert loaded.broken_symlinks[0].candidate_score == 95.0
        assert len(loaded.misplaced_symlinks) == 1
        assert loaded.misplaced_symlinks[0].media_title == "Film Action"
        assert len(loaded.oversized_dirs) == 1
        assert loaded.oversized_dirs[0].current_count == 60
        assert len(loaded.oversized_dirs[0].items_to_move) == 1
        assert len(loaded.empty_dirs) == 1
        assert loaded.not_in_db_count == 5

    def test_load_cache_expired(self, tmp_path):
        """Un cache trop vieux est ignore."""
        import time
        from src.services.cleanup import save_report_cache, load_report_cache

        video_dir = tmp_path / "video"
        cache_dir = tmp_path / "cache"

        report = CleanupReport(
            video_dir=video_dir,
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
        )

        save_report_cache(report, cache_dir=cache_dir)

        # Modifier le mtime du fichier cache pour simuler l'expiration
        cache_file = cache_dir / "cleanup_report.json"
        old_time = time.time() - 20 * 60  # 20 minutes ago
        os.utime(cache_file, (old_time, old_time))

        loaded = load_report_cache(video_dir, max_age_minutes=10, cache_dir=cache_dir)
        assert loaded is None

    def test_load_cache_wrong_video_dir(self, tmp_path):
        """Un cache pour un autre video_dir est ignore."""
        from src.services.cleanup import save_report_cache, load_report_cache

        cache_dir = tmp_path / "cache"

        report = CleanupReport(
            video_dir=tmp_path / "video_a",
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
        )

        save_report_cache(report, cache_dir=cache_dir)

        # Charger avec un autre video_dir
        loaded = load_report_cache(tmp_path / "video_b", cache_dir=cache_dir)
        assert loaded is None

    def test_load_cache_missing_file(self, tmp_path):
        """Retourne None si le fichier cache n'existe pas."""
        from src.services.cleanup import load_report_cache

        loaded = load_report_cache(tmp_path / "video", cache_dir=tmp_path / "nonexistent")
        assert loaded is None

    def test_save_report_empty(self, tmp_path):
        """Sauvegarde et chargement d'un rapport vide."""
        from src.services.cleanup import save_report_cache, load_report_cache

        video_dir = tmp_path / "video"
        cache_dir = tmp_path / "cache"

        report = CleanupReport(
            video_dir=video_dir,
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
            not_in_db_count=0,
        )

        save_report_cache(report, cache_dir=cache_dir)
        loaded = load_report_cache(video_dir, cache_dir=cache_dir)

        assert loaded is not None
        assert loaded.total_issues == 0
        assert loaded.not_in_db_count == 0

    def test_broken_symlink_no_candidate(self, tmp_path):
        """BrokenSymlinkInfo sans candidat est correctement serialise."""
        from src.services.cleanup import save_report_cache, load_report_cache

        video_dir = tmp_path / "video"
        cache_dir = tmp_path / "cache"

        report = CleanupReport(
            video_dir=video_dir,
            broken_symlinks=[
                BrokenSymlinkInfo(
                    symlink_path=Path("/video/Films/broken.mkv"),
                    original_target=Path("/storage/old.mkv"),
                    best_candidate=None,
                    candidate_score=0.0,
                ),
            ],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
        )

        save_report_cache(report, cache_dir=cache_dir)
        loaded = load_report_cache(video_dir, cache_dir=cache_dir)

        assert loaded is not None
        assert loaded.broken_symlinks[0].best_candidate is None
        assert loaded.broken_symlinks[0].candidate_score == 0.0
