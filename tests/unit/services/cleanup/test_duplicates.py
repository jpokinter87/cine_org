"""Tests pour les symlinks dupliques."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.services.cleanup import (
    CleanupReport,
    CleanupResult,
    CleanupStepType,
    DuplicateSymlink,
)


# ============================================================================
# Phase 9 : Symlinks dupliques
# ============================================================================


class TestDuplicateSymlinkDataclass:
    """Tests pour la dataclass DuplicateSymlink."""

    def test_duplicate_symlink_creation(self):
        """DuplicateSymlink stocke les champs correctement."""
        dup = DuplicateSymlink(
            directory=Path("/video/Films/Action"),
            target_path=Path("/storage/Films/film.mkv"),
            keep=Path("/video/Films/Action/Film (2020) MULTi x264 1080p.mkv"),
            remove=[Path("/video/Films/Action/Film (2020) MULTi 1080p.mkv")],
        )
        assert dup.directory == Path("/video/Films/Action")
        assert dup.target_path == Path("/storage/Films/film.mkv")
        assert len(dup.remove) == 1

    def test_cleanup_report_includes_duplicate_symlinks(self):
        """CleanupReport.total_issues inclut les symlinks dupliques."""
        dup = DuplicateSymlink(
            directory=Path("/video/Films/Action"),
            target_path=Path("/storage/Films/film.mkv"),
            keep=Path("/video/Films/Action/Film (2020) MULTi x264 1080p.mkv"),
            remove=[Path("/video/Films/Action/Film (2020) MULTi 1080p.mkv")],
        )
        report = CleanupReport(
            video_dir=Path("/video"),
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
            duplicate_symlinks=[dup],
        )
        assert report.has_issues is True
        assert report.total_issues == 1

    def test_cleanup_step_type_duplicate(self):
        """CleanupStepType.DUPLICATE_SYMLINK existe."""
        assert CleanupStepType.DUPLICATE_SYMLINK == "duplicate_symlink"


class TestScanDuplicateSymlinks:
    """Tests pour _scan_duplicate_symlinks."""

    def test_detect_duplicate_symlinks(self, cleanup_service, temp_dirs):
        """Deux symlinks dans le meme repertoire pointant vers la meme cible."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer le fichier physique cible
        target = storage_dir / "Films" / "Action" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        # Creer deux symlinks dans le meme repertoire pointant vers la meme cible
        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        old_link = action_dir / "Film (2020) MULTi 1080p.mkv"
        old_link.symlink_to(target)

        new_link = action_dir / "Film (2020) MULTi x264 1080p.mkv"
        new_link.symlink_to(target)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 1
        assert result[0].target_path == target.resolve()
        assert result[0].keep == new_link  # Nom le plus long
        assert old_link in result[0].remove

    def test_no_duplicates(self, cleanup_service, temp_dirs):
        """Symlinks differents vers des cibles differentes -> pas de doublon."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer deux fichiers physiques distincts
        target1 = storage_dir / "Films" / "film1.mkv"
        target1.parent.mkdir(parents=True)
        target1.touch()
        target2 = storage_dir / "Films" / "film2.mkv"
        target2.touch()

        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        link1 = action_dir / "Film 1 (2020).mkv"
        link1.symlink_to(target1)
        link2 = action_dir / "Film 2 (2020).mkv"
        link2.symlink_to(target2)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 0

    def test_same_target_different_dirs_not_duplicate(self, cleanup_service, temp_dirs):
        """Meme cible mais dans des repertoires differents -> pas de doublon."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        target = storage_dir / "Films" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        # Deux symlinks vers la meme cible mais dans des repertoires differents
        dir1 = video_dir / "Films" / "Action"
        dir1.mkdir(parents=True)
        dir2 = video_dir / "Films" / "Drame"
        dir2.mkdir(parents=True)

        link1 = dir1 / "Film (2020).mkv"
        link1.symlink_to(target)
        link2 = dir2 / "Film (2020).mkv"
        link2.symlink_to(target)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 0

    def test_heuristic_keeps_longest_name(self, cleanup_service, temp_dirs):
        """Le symlink avec le nom le plus long est conserve."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        target = storage_dir / "Films" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        # 3 symlinks de longueurs differentes
        short = action_dir / "Film (2020).mkv"
        short.symlink_to(target)
        medium = action_dir / "Film (2020) MULTi 1080p.mkv"
        medium.symlink_to(target)
        long = action_dir / "Film (2020) MULTi x264 DTS 1080p.mkv"
        long.symlink_to(target)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 1
        assert result[0].keep == long
        assert set(result[0].remove) == {short, medium}

    def test_scope_ignores_outside_films_series(self, cleanup_service, temp_dirs):
        """Les doublons hors Films/ et Series/ sont ignores."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        target = storage_dir / "doc.mkv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

        # Doublons hors scope (Documentaires)
        docs_dir = video_dir / "Documentaires"
        docs_dir.mkdir(parents=True)
        (docs_dir / "Doc (2020).mkv").symlink_to(target)
        (docs_dir / "Doc (2020) FR.mkv").symlink_to(target)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 0

    def test_broken_symlinks_ignored(self, cleanup_service, temp_dirs):
        """Les symlinks casses ne sont pas comptes comme doublons."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        target = storage_dir / "Films" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        # Un symlink valide
        valid = action_dir / "Film (2020) MULTi x264 1080p.mkv"
        valid.symlink_to(target)

        # Un symlink casse (vers une cible qui n'existe pas)
        broken = action_dir / "Film (2020) MULTi 1080p.mkv"
        broken.symlink_to(storage_dir / "Films" / "inexistant.mkv")

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 0

    def test_series_duplicate_symlinks(self, cleanup_service, temp_dirs):
        """Doublons dans Séries/ sont aussi detectes."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        target = storage_dir / "Séries" / "episode.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        season_dir = video_dir / "Séries" / "B" / "Breaking Bad (2008)" / "Saison 01"
        season_dir.mkdir(parents=True)

        old_link = season_dir / "Breaking Bad (2008) - S01E01 - Pilot.mkv"
        old_link.symlink_to(target)
        new_link = season_dir / "Breaking Bad (2008) - S01E01 - Pilot - MULTi x264 1080p.mkv"
        new_link.symlink_to(target)

        result = cleanup_service._scan_duplicate_symlinks(video_dir)

        assert len(result) == 1
        assert result[0].keep == new_link
        assert old_link in result[0].remove


class TestFixDuplicateSymlinks:
    """Tests pour fix_duplicate_symlinks."""

    def test_fix_removes_duplicate_symlinks(self, cleanup_service, tmp_path):
        """fix_duplicate_symlinks supprime les doublons et garde le bon."""
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        target = storage_dir / "film.mkv"
        target.touch()

        action_dir = tmp_path / "video" / "Films" / "Action"
        action_dir.mkdir(parents=True)

        keep_link = action_dir / "Film (2020) MULTi x264 1080p.mkv"
        keep_link.symlink_to(target)
        remove_link = action_dir / "Film (2020) MULTi 1080p.mkv"
        remove_link.symlink_to(target)

        duplicates = [
            DuplicateSymlink(
                directory=action_dir,
                target_path=target,
                keep=keep_link,
                remove=[remove_link],
            ),
        ]

        result = cleanup_service.fix_duplicate_symlinks(duplicates)

        assert result.duplicate_symlinks_removed == 1
        assert keep_link.is_symlink()  # Conserve
        assert not remove_link.exists()  # Supprime

    def test_fix_multiple_removes(self, cleanup_service, tmp_path):
        """fix_duplicate_symlinks supprime plusieurs doublons pour un meme target."""
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        target = storage_dir / "film.mkv"
        target.touch()

        action_dir = tmp_path / "video" / "Films" / "Action"
        action_dir.mkdir(parents=True)

        keep = action_dir / "Film (2020) MULTi x264 DTS 1080p.mkv"
        keep.symlink_to(target)
        remove1 = action_dir / "Film (2020).mkv"
        remove1.symlink_to(target)
        remove2 = action_dir / "Film (2020) MULTi 1080p.mkv"
        remove2.symlink_to(target)

        duplicates = [
            DuplicateSymlink(
                directory=action_dir,
                target_path=target,
                keep=keep,
                remove=[remove1, remove2],
            ),
        ]

        result = cleanup_service.fix_duplicate_symlinks(duplicates)

        assert result.duplicate_symlinks_removed == 2
        assert keep.is_symlink()
        assert not remove1.exists()
        assert not remove2.exists()

    def test_fix_already_removed(self, cleanup_service, tmp_path):
        """fix_duplicate_symlinks gere gracieusement un symlink deja supprime."""
        action_dir = tmp_path / "video" / "Films" / "Action"
        action_dir.mkdir(parents=True)

        target = tmp_path / "storage" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        keep = action_dir / "Film (2020) MULTi x264 1080p.mkv"
        keep.symlink_to(target)

        # Le symlink a supprimer n'existe deja plus
        ghost = action_dir / "Film (2020).mkv"

        duplicates = [
            DuplicateSymlink(
                directory=action_dir,
                target_path=target,
                keep=keep,
                remove=[ghost],
            ),
        ]

        result = cleanup_service.fix_duplicate_symlinks(duplicates)

        # Pas d'erreur, mais pas comptabilise non plus
        assert result.duplicate_symlinks_removed == 0
        assert len(result.errors) == 1


class TestCleanupResultDuplicateField:
    """Tests pour le champ duplicate_symlinks_removed dans CleanupResult."""

    def test_cleanup_result_default(self):
        """CleanupResult a duplicate_symlinks_removed=0 par defaut."""
        result = CleanupResult()
        assert result.duplicate_symlinks_removed == 0


class TestDuplicateSymlinkCache:
    """Tests pour la serialisation/deserialisation des doublons dans le cache."""

    def test_save_and_load_with_duplicates(self, tmp_path):
        """Sauvegarde et rechargement d'un rapport avec doublons."""
        from src.services.cleanup import save_report_cache, load_report_cache

        video_dir = tmp_path / "video"
        cache_dir = tmp_path / "cache"

        dup = DuplicateSymlink(
            directory=Path("/video/Films/Action"),
            target_path=Path("/storage/Films/film.mkv"),
            keep=Path("/video/Films/Action/Film (2020) MULTi x264 1080p.mkv"),
            remove=[
                Path("/video/Films/Action/Film (2020) MULTi 1080p.mkv"),
                Path("/video/Films/Action/Film (2020).mkv"),
            ],
        )

        report = CleanupReport(
            video_dir=video_dir,
            broken_symlinks=[],
            misplaced_symlinks=[],
            oversized_dirs=[],
            empty_dirs=[],
            duplicate_symlinks=[dup],
        )

        save_report_cache(report, cache_dir=cache_dir)
        loaded = load_report_cache(video_dir, cache_dir=cache_dir)

        assert loaded is not None
        assert len(loaded.duplicate_symlinks) == 1
        assert loaded.duplicate_symlinks[0].directory == Path("/video/Films/Action")
        assert loaded.duplicate_symlinks[0].target_path == Path("/storage/Films/film.mkv")
        assert loaded.duplicate_symlinks[0].keep == Path("/video/Films/Action/Film (2020) MULTi x264 1080p.mkv")
        assert len(loaded.duplicate_symlinks[0].remove) == 2

    def test_load_cache_without_duplicates_field(self, tmp_path):
        """Un cache sans le champ duplicate_symlinks est charge avec une liste vide."""
        import json
        import time

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        video_dir = tmp_path / "video"

        # Ecrire un cache JSON sans le champ duplicate_symlinks (ancien format)
        data = {
            "video_dir": str(video_dir),
            "not_in_db_count": 0,
            "broken_symlinks": [],
            "misplaced_symlinks": [],
            "oversized_dirs": [],
            "empty_dirs": [],
        }
        cache_file = cache_dir / "cleanup_report.json"
        cache_file.write_text(json.dumps(data))

        from src.services.cleanup import load_report_cache
        loaded = load_report_cache(video_dir, cache_dir=cache_dir)

        assert loaded is not None
        assert loaded.duplicate_symlinks == []


class TestAnalyzeIncludesDuplicates:
    """Tests verifiant que analyze() appelle _scan_duplicate_symlinks."""

    def test_analyze_includes_duplicate_scan(
        self, cleanup_service, mock_repair_service, temp_dirs,
    ):
        """analyze() retourne les symlinks dupliques dans le rapport."""
        video_dir = temp_dirs["video"]
        storage_dir = temp_dirs["storage"]

        # Creer un doublon dans Films/
        target = storage_dir / "Films" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        old_link = action_dir / "Film (2020) MULTi 1080p.mkv"
        old_link.symlink_to(target)
        new_link = action_dir / "Film (2020) MULTi x264 1080p.mkv"
        new_link.symlink_to(target)

        report = cleanup_service.analyze(video_dir)

        assert len(report.duplicate_symlinks) == 1
        assert report.total_issues >= 1
