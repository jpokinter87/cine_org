"""
Tests pour IntegrityChecker et RepairService - verification et reparation.

TDD tests couvrant:
- Detection des entrees fantomes (ghost_entry)
- Detection des fichiers orphelins (orphan_file)
- Detection des symlinks casses (broken_symlink)
- Format rapport JSON
- Recherche de cibles possibles
- Deplacement vers orphans
- Sauvegarde du log de reparation
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.integrity import (
    IntegrityChecker,
    IntegrityIssue,
    IntegrityReport,
    IssueType,
    RepairAction,
    RepairActionType,
)
from src.services.repair import RepairService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_file_system():
    """Create a mock FileSystemAdapter."""
    fs = MagicMock()
    fs.exists = MagicMock(return_value=True)
    fs.find_broken_links = MagicMock(return_value=[])
    fs.create_symlink = MagicMock(return_value=True)
    return fs


@pytest.fixture
def mock_video_file_repo():
    """Create a mock VideoFileRepository with session."""
    repo = MagicMock()
    repo.get_by_path = MagicMock(return_value=None)
    # Mock session pour les requetes directes
    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = []
    repo._session = mock_session
    return repo


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing."""
    storage_dir = tmp_path / "storage"
    video_dir = tmp_path / "video"
    trash_dir = tmp_path / "trash"

    storage_dir.mkdir()
    video_dir.mkdir()
    trash_dir.mkdir()

    return {
        "storage": storage_dir,
        "video": video_dir,
        "trash": trash_dir,
    }


@pytest.fixture
def integrity_checker(mock_file_system, mock_video_file_repo, temp_dirs):
    """Create an IntegrityChecker with mocks."""
    return IntegrityChecker(
        file_system=mock_file_system,
        video_file_repo=mock_video_file_repo,
        storage_dir=temp_dirs["storage"],
        video_dir=temp_dirs["video"],
    )


@pytest.fixture
def repair_service(mock_file_system, mock_video_file_repo, temp_dirs):
    """Create a RepairService with mocks."""
    return RepairService(
        file_system=mock_file_system,
        video_file_repo=mock_video_file_repo,
        storage_dir=temp_dirs["storage"],
        video_dir=temp_dirs["video"],
        trash_dir=temp_dirs["trash"],
    )


# ============================================================================
# Tests: IntegrityChecker - Ghost Entries
# ============================================================================


class TestIntegrityCheckerGhostEntries:
    """Tests for ghost entry detection."""

    def test_check_finds_ghost_entries(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Entree BDD sans fichier physique -> ghost_entry."""
        # Setup: model en BDD avec path inexistant
        mock_model = MagicMock()
        mock_model.id = 1
        mock_model.path = str(temp_dirs["storage"] / "fantome.mkv")

        mock_video_file_repo._session.exec.return_value.all.return_value = [mock_model]

        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
        )

        report = checker.check()

        assert report.has_issues is True
        assert len(report.ghost_entries) == 1
        assert report.ghost_entries[0].type == IssueType.GHOST_ENTRY
        assert "fantome.mkv" in str(report.ghost_entries[0].path)


# ============================================================================
# Tests: IntegrityChecker - Orphan Files
# ============================================================================


class TestIntegrityCheckerOrphanFiles:
    """Tests for orphan file detection."""

    def test_check_finds_orphan_files(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Fichier physique sans entree BDD -> orphan_file."""
        # Setup: creer un fichier dans storage qui n'est pas en BDD
        orphan_file = temp_dirs["storage"] / "orphan.mkv"
        orphan_file.write_text("fake video content")

        # get_by_path retourne None (pas en BDD)
        mock_video_file_repo.get_by_path.return_value = None

        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
        )

        report = checker.check()

        assert report.has_issues is True
        assert len(report.orphan_files) == 1
        assert report.orphan_files[0].type == IssueType.ORPHAN_FILE
        assert "orphan.mkv" in str(report.orphan_files[0].path)

    def test_check_ignores_non_video_files(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Les fichiers non-video ne sont pas signales comme orphelins."""
        # Creer un fichier non-video
        non_video = temp_dirs["storage"] / "readme.txt"
        non_video.write_text("documentation")

        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
        )

        report = checker.check()

        # Aucun orphelin video
        assert len(report.orphan_files) == 0


# ============================================================================
# Tests: IntegrityChecker - Broken Symlinks
# ============================================================================


class TestIntegrityCheckerBrokenSymlinks:
    """Tests for broken symlink detection."""

    def test_check_finds_broken_symlinks(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Symlink casse dans video/ -> broken_symlink."""
        # Setup: file_system.find_broken_links retourne un lien casse
        broken_link = temp_dirs["video"] / "broken.mkv"
        mock_file_system.find_broken_links.return_value = [broken_link]

        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
        )

        # Mock readlink pour le lien casse
        with patch.object(Path, "readlink", return_value=Path("/storage/missing.mkv")):
            report = checker.check()

        assert report.has_issues is True
        assert len(report.broken_symlinks) == 1
        assert report.broken_symlinks[0].type == IssueType.BROKEN_SYMLINK


# ============================================================================
# Tests: IntegrityReport
# ============================================================================


class TestIntegrityReport:
    """Tests for IntegrityReport."""

    def test_integrity_report_to_json(self):
        """Format JSON valide avec toutes les sections."""
        report = IntegrityReport(
            issues=[
                IntegrityIssue(
                    type=IssueType.GHOST_ENTRY,
                    path=Path("/storage/ghost.mkv"),
                    details="ID BDD: 1",
                ),
                IntegrityIssue(
                    type=IssueType.ORPHAN_FILE,
                    path=Path("/storage/orphan.mkv"),
                ),
                IntegrityIssue(
                    type=IssueType.BROKEN_SYMLINK,
                    path=Path("/video/broken.mkv"),
                    details="/storage/missing.mkv",
                ),
            ],
            suggestions=["cineorg repair-links"],
        )

        json_str = report.to_json()
        parsed = json.loads(json_str)

        assert parsed["has_issues"] is True
        assert parsed["summary"]["total"] == 3
        assert parsed["summary"]["ghost_entries"] == 1
        assert parsed["summary"]["orphan_files"] == 1
        assert parsed["summary"]["broken_symlinks"] == 1
        assert len(parsed["issues"]) == 3
        assert len(parsed["suggestions"]) == 1

    def test_integrity_report_format_text(self):
        """Format texte structure avec sections."""
        report = IntegrityReport(
            issues=[
                IntegrityIssue(
                    type=IssueType.BROKEN_SYMLINK,
                    path=Path("/video/broken.mkv"),
                    details="/storage/missing.mkv",
                ),
            ],
            suggestions=["cineorg repair-links"],
        )

        text = report.format_text()

        assert "Rapport d'integrite" in text
        assert "Symlinks casses" in text
        assert "broken.mkv" in text
        assert "repair-links" in text

    def test_integrity_report_empty(self):
        """Rapport sans issues."""
        report = IntegrityReport()

        assert report.has_issues is False
        text = report.format_text()
        assert "Aucune incoherence" in text


# ============================================================================
# Tests: RepairService - find_possible_targets
# ============================================================================


class TestRepairServiceFindTargets:
    """Tests for find_possible_targets."""

    def test_find_possible_targets(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Trouve un fichier avec le meme nom dans storage."""
        # Creer un fichier dans storage
        target_file = temp_dirs["storage"] / "Films" / "Avatar.mkv"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("fake video")

        # Lien casse pointant vers un fichier du meme nom
        broken_link = temp_dirs["video"] / "Avatar.mkv"

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        targets = service.find_possible_targets(broken_link)

        assert len(targets) >= 1
        assert any("Avatar.mkv" in str(t) for t in targets)

    def test_find_possible_targets_no_match(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Aucune cible trouvee si storage vide."""
        broken_link = temp_dirs["video"] / "Unknown.mkv"

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        targets = service.find_possible_targets(broken_link)

        assert len(targets) == 0


# ============================================================================
# Tests: RepairService - move_to_orphans
# ============================================================================


class TestRepairServiceMoveToOrphans:
    """Tests for move_to_orphans."""

    def test_move_to_orphans_creates_directory(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Cree trash/orphans si necessaire."""
        # Supprimer le dossier orphans s'il existe
        orphans_dir = temp_dirs["trash"] / "orphans"
        if orphans_dir.exists():
            orphans_dir.rmdir()

        # Creer un faux lien dans video
        broken_link = temp_dirs["video"] / "orphan.mkv"
        broken_link.symlink_to(temp_dirs["storage"] / "missing.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        result = service.move_to_orphans(broken_link)

        # Verifie que le dossier orphans a ete cree
        assert orphans_dir.exists()
        assert result is not None
        assert "orphans" in str(result)

    def test_move_to_orphans_handles_conflict(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Ajoute timestamp si fichier existe deja."""
        # Creer le dossier orphans avec un fichier existant
        orphans_dir = temp_dirs["trash"] / "orphans"
        orphans_dir.mkdir(parents=True, exist_ok=True)
        existing = orphans_dir / "conflict.mkv"
        existing.write_text("existing")

        # Creer un lien avec le meme nom
        broken_link = temp_dirs["video"] / "conflict.mkv"
        broken_link.symlink_to(temp_dirs["storage"] / "missing.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        result = service.move_to_orphans(broken_link)

        # Le fichier doit avoir un timestamp dans le nom
        assert result is not None
        assert result.name != "conflict.mkv"
        assert "conflict" in result.name


# ============================================================================
# Tests: RepairService - save_log
# ============================================================================


class TestRepairServiceSaveLog:
    """Tests for save_log."""

    def test_save_log_writes_file(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Fichier log cree avec actions."""
        actions = [
            RepairAction(
                link=Path("/video/repaired.mkv"),
                action=RepairActionType.REPAIRED,
                new_target=Path("/storage/repaired.mkv"),
            ),
            RepairAction(
                link=Path("/video/orphaned.mkv"),
                action=RepairActionType.ORPHANED,
            ),
            RepairAction(
                link=Path("/video/skipped.mkv"),
                action=RepairActionType.SKIPPED,
            ),
        ]

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        log_path = service.save_log(actions)

        assert log_path is not None
        assert log_path.exists()
        assert "repair-" in log_path.name
        assert log_path.suffix == ".log"

        # Verifier le contenu
        with open(log_path) as f:
            data = json.load(f)

        assert data["actions_count"] == 3
        assert data["summary"]["repaired"] == 1
        assert data["summary"]["orphaned"] == 1
        assert data["summary"]["skipped"] == 1

    def test_save_log_empty_actions(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Pas de fichier cree si aucune action."""
        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        log_path = service.save_log([])

        assert log_path is None


# ============================================================================
# Tests: RepairService - repair_symlink
# ============================================================================


class TestRepairServiceRepairSymlink:
    """Tests for repair_symlink."""

    def test_repair_symlink_success(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Repare un symlink avec une nouvelle cible."""
        # Creer un lien casse
        broken_link = temp_dirs["video"] / "torepair.mkv"
        broken_link.symlink_to(temp_dirs["storage"] / "old_target.mkv")

        # Nouvelle cible
        new_target = temp_dirs["storage"] / "new_target.mkv"
        new_target.write_text("new content")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=temp_dirs["trash"],
        )

        result = service.repair_symlink(broken_link, new_target)

        assert result is True
        mock_file_system.create_symlink.assert_called_once_with(new_target, broken_link)


# ============================================================================
# Tests: IntegrityChecker - Suggestions
# ============================================================================


class TestIntegrityCheckerSuggestions:
    """Tests for suggestion generation."""

    def test_suggestions_for_broken_symlinks(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """Suggere repair-links pour les symlinks casses."""
        broken_link = temp_dirs["video"] / "broken.mkv"
        mock_file_system.find_broken_links.return_value = [broken_link]

        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
        )

        with patch.object(Path, "readlink", return_value=Path("/missing")):
            report = checker.check()

        assert any("repair-links" in s for s in report.suggestions)


# ============================================================================
# Tests: Edge Cases
# ============================================================================


class TestIntegrityEdgeCases:
    """Tests for edge cases."""

    def test_checker_without_dirs(self, mock_file_system, mock_video_file_repo):
        """Checker fonctionne sans storage_dir et video_dir."""
        checker = IntegrityChecker(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=None,
            video_dir=None,
        )

        report = checker.check()

        # Ne devrait pas lever d'erreur
        assert isinstance(report, IntegrityReport)

    def test_repair_without_trash_dir(
        self, mock_file_system, mock_video_file_repo, temp_dirs
    ):
        """move_to_orphans retourne None sans trash_dir."""
        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=temp_dirs["storage"],
            video_dir=temp_dirs["video"],
            trash_dir=None,
        )

        broken_link = temp_dirs["video"] / "test.mkv"
        broken_link.symlink_to(temp_dirs["storage"] / "missing.mkv")

        result = service.move_to_orphans(broken_link)

        assert result is None

# ============================================================================
# Tests: RepairService - _find_regroup_candidates (recherche ciblée)
# ============================================================================


class TestFindRegroupCandidates:
    """Tests pour la recherche ciblée dans le répertoire NAS parent."""

    def test_finds_candidates_in_nas_parent_directory(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Trouve les fichiers dans le répertoire NAS parent quand le préfixe n'existe pas."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Structure NAS : les fichiers sont dans Fantomas/ (pas dans Fantomas/Fantômas/)
        nas_dir = storage / "Films" / "Comédie" / "A-H" / "F" / "Fantomas"
        nas_dir.mkdir(parents=True)
        (nas_dir / "Fantomas.1964.FRENCH.1080p.HEVC.mkv").write_text("video1")
        (nas_dir / "Fantomas.contre.Scotland.Yard.1967.FRENCH.1080p.mkv").write_text("video2")
        (nas_dir / "Fantomas.se.dechaine.1965.FRENCH.1080p.mkv").write_text("video3")

        # Symlink brisé : pointe vers .../Fantomas/Fantômas/filename (n'existe pas)
        video_dir = video / "Films" / "Comédie" / "A-H" / "F" / "Fantomas" / "Fantômas"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Fantômas (1964) FR HEVC 1080p.mkv"
        broken_target = nas_dir / "Fantômas" / "Fantômas (1964) FR HEVC 1080p.mkv"
        broken_link.symlink_to(broken_target)

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        # Doit trouver les 3 fichiers du répertoire parent
        assert len(candidates) == 3
        filenames = [p.name for p, _ in candidates]
        assert "Fantomas.1964.FRENCH.1080p.HEVC.mkv" in filenames

    def test_finds_candidates_when_parent_exists_with_other_files(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Trouve les fichiers dans le parent quand le fichier cible manque."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Le répertoire cible existe avec un autre fichier
        nas_dir = storage / "Films" / "existing"
        nas_dir.mkdir(parents=True)
        (nas_dir / "somefile.mkv").write_text("video")

        # Symlink qui pointe vers un fichier manquant DANS un répertoire existant
        video_dir = video / "Films"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "missing.mkv"
        broken_link.symlink_to(nas_dir / "missing.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        # Le parent existe et contient un fichier → candidat proposé
        assert len(candidates) == 1
        assert candidates[0][0].name == "somefile.mkv"

    def test_returns_empty_when_grandparent_missing(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Pas de candidats si le grand-parent n'existe pas non plus."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        video_dir = video / "Films"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "test.mkv"
        # Cible avec deux niveaux manquants
        broken_link.symlink_to(storage / "missing1" / "missing2" / "test.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        assert len(candidates) == 0

    def test_candidates_sorted_by_score(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Les candidats sont triés par score de similarité décroissant."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        nas_dir = storage / "Films" / "F"
        nas_dir.mkdir(parents=True)
        # Fichier très similaire
        (nas_dir / "Fantomas.1964.FRENCH.mkv").write_text("video1")
        # Fichier moins similaire
        (nas_dir / "Totally.Different.Movie.2020.mkv").write_text("video2")

        video_dir = video / "Films" / "F" / "Fantomas"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Fantômas (1964) FR 1080p.mkv"
        broken_link.symlink_to(nas_dir / "Fantomas" / "Fantômas (1964) FR 1080p.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        assert len(candidates) == 2
        # Le plus similaire en premier
        assert "Fantomas" in candidates[0][0].name
        assert candidates[0][1] >= candidates[1][1]

    def test_only_video_files_returned(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Seuls les fichiers vidéo sont retournés comme candidats."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        nas_dir = storage / "Films" / "F"
        nas_dir.mkdir(parents=True)
        (nas_dir / "Fantomas.mkv").write_text("video")
        (nas_dir / "Fantomas.nfo").write_text("info")
        (nas_dir / "Fantomas.srt").write_text("subs")
        (nas_dir / "cover.jpg").write_bytes(b"image")

        video_dir = video / "Films" / "F" / "Fantomas"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Fantômas (1964).mkv"
        broken_link.symlink_to(nas_dir / "Fantomas" / "Fantômas (1964).mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        assert len(candidates) == 1
        assert candidates[0][0].name == "Fantomas.mkv"

    def test_finds_candidates_when_parent_exists_with_files(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Trouve les fichiers dans le parent NAS existant quand le fichier cible manque."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Le répertoire préfixe NAS EXISTE et contient des fichiers
        nas_prefix_dir = storage / "Documentaire" / "DCDL"
        nas_prefix_dir.mkdir(parents=True)
        (nas_prefix_dir / "DCDL.Ils.Etaient.La.France.Libre.FRENCH.720p.avi").write_text("v1")
        (nas_prefix_dir / "DCDL.Le.Jour.J.FRENCH.720p.avi").write_text("v2")

        # Symlink brisé : pointe vers un fichier avec nom différent dans le même répertoire
        video_dir = video / "Documentaire" / "DCDL"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "DCDL - Ils étaient la France libre.avi"
        broken_link.symlink_to(nas_prefix_dir / "DCDL - Ils étaient la France libre.avi")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        # Doit trouver les 2 fichiers du répertoire
        assert len(candidates) == 2
        filenames = [p.name for p, _ in candidates]
        assert "DCDL.Ils.Etaient.La.France.Libre.FRENCH.720p.avi" in filenames

    def test_returns_empty_when_parent_exists_but_empty(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Pas de candidats si le parent existe mais est vide."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Répertoire vide sur NAS
        nas_prefix_dir = storage / "Documentaire" / "Prefix"
        nas_prefix_dir.mkdir(parents=True)

        video_dir = video / "Documentaire" / "Prefix"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Some File (2020).mkv"
        broken_link.symlink_to(nas_prefix_dir / "Some File (2020).mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        assert len(candidates) == 0

    def test_searches_both_parent_and_grandparent(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Cherche dans parent ET grand-parent quand le parent existe."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Grand-parent : contient le vrai fichier (nom original)
        grandparent_dir = storage / "Films" / "Policier" / "A"
        grandparent_dir.mkdir(parents=True)
        (grandparent_dir / "Fallen.Angels.1995.MULTi.1080p.mkv").write_text("video1")

        # Parent (préfixe) : existe mais contient un autre film
        parent_dir = grandparent_dir / "Ange"
        parent_dir.mkdir()
        (parent_dir / "Les Anges de la nuit (1990).mkv").write_text("video2")

        # Symlink brisé pointe vers parent/nom_absent
        video_dir = video / "Films" / "Policier" / "A" / "Ange"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Les Anges déchus (1995).mkv"
        broken_link.symlink_to(parent_dir / "Les Anges déchus (1995).mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        candidates = service._find_regroup_candidates(broken_link)

        # Doit trouver les fichiers des DEUX répertoires
        assert len(candidates) == 2
        filenames = [p.name for p, _ in candidates]
        assert "Fallen.Angels.1995.MULTi.1080p.mkv" in filenames
        assert "Les Anges de la nuit (1990).mkv" in filenames

    def test_alternative_names_improves_matching(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Les titres alternatifs (ex: titre original TMDB) améliorent le scoring."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # NAS : fichier avec le titre original anglais
        nas_dir = storage / "Films" / "A"
        nas_dir.mkdir(parents=True)
        (nas_dir / "Fallen.Angels.1995.MULTi.1080p.BluRay.mkv").write_text("video")

        # Symlink brisé avec le titre français
        video_dir = video / "Films" / "A" / "Ange"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Les Anges déchus (1995) MULTi HEVC 1080p.mkv"
        broken_link.symlink_to(nas_dir / "Ange" / "Les Anges déchus (1995) MULTi HEVC 1080p.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        # Sans titre alternatif : score bas (FR vs EN)
        candidates_without = service._find_regroup_candidates(broken_link)
        score_without = candidates_without[0][1] if candidates_without else 0

        # Avec titre original : score amélioré
        candidates_with = service._find_regroup_candidates(
            broken_link, alternative_names=["Fallen Angels (1995).mkv"]
        )
        score_with = candidates_with[0][1] if candidates_with else 0

        assert score_with > score_without

    def test_find_possible_targets_tries_regroup_first(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """find_possible_targets essaie d'abord la recherche regroup ciblée."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Fichier NAS dans le répertoire parent
        nas_dir = storage / "Films" / "F"
        nas_dir.mkdir(parents=True)
        (nas_dir / "Fantomas.1964.FRENCH.1080p.mkv").write_text("video")

        # Symlink brisé par regroup
        video_dir = video / "Films" / "F" / "Fantomas"
        video_dir.mkdir(parents=True)
        broken_link = video_dir / "Fantômas (1964) FR 1080p.mkv"
        broken_link.symlink_to(nas_dir / "Fantomas" / "Fantômas (1964) FR 1080p.mkv")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=video,
        )

        # Pas besoin de build_file_index : la recherche regroup est directe
        candidates = service.find_possible_targets(broken_link)

        assert len(candidates) >= 1
        assert "Fantomas.1964.FRENCH.1080p.mkv" in candidates[0][0].name


# ============================================================================
# Tests: RepairService - build_file_index avec scan_all
# ============================================================================


class TestBuildFileIndex:
    """Tests pour build_file_index avec paramètre scan_all."""

    def test_build_file_index_default_scans_films_series_only(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Par défaut, seuls Films/ et Séries/ sont scannés."""
        storage = tmp_path / "storage"
        storage.mkdir()

        # Créer des fichiers dans Films et Documentaire
        films_dir = storage / "Films"
        films_dir.mkdir()
        (films_dir / "Avatar (2009).mkv").write_text("video")

        doc_dir = storage / "Documentaire"
        doc_dir.mkdir()
        (doc_dir / "Planet Earth (2006).mkv").write_text("video")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True)

        # Seul Films est scanné
        assert count == 1
        paths = [str(p) for p, _, _ in service._file_index]
        assert any("Avatar" in p for p in paths)
        assert not any("Planet" in p for p in paths)

    def test_build_file_index_scan_all_includes_all_categories(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Avec scan_all=True, toutes les catégories sont scannées."""
        storage = tmp_path / "storage"
        storage.mkdir()

        # Créer des fichiers dans différentes catégories
        for category, filename in [
            ("Films", "Avatar (2009).mkv"),
            ("Séries", "Breaking Bad S01E01.mkv"),
            ("Documentaire", "Planet Earth (2006).mkv"),
            ("Éducatif", "Cours de Python (2024).mkv"),
            ("Musique", "Concert Live (2023).mkv"),
        ]:
            cat_dir = storage / category
            cat_dir.mkdir()
            (cat_dir / filename).write_text("video")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True, scan_all=True)

        # Tous les fichiers de toutes les catégories sont scannés
        assert count == 5
        paths = [str(p) for p, _, _ in service._file_index]
        assert any("Avatar" in p for p in paths)
        assert any("Breaking" in p for p in paths)
        assert any("Planet" in p for p in paths)
        assert any("Cours" in p for p in paths)
        assert any("Concert" in p for p in paths)

    def test_build_file_index_scan_all_excludes_non_video_files(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """scan_all=True n'indexe que les fichiers vidéo."""
        storage = tmp_path / "storage"
        storage.mkdir()

        doc_dir = storage / "Documentaire"
        doc_dir.mkdir()
        (doc_dir / "Planet Earth (2006).mkv").write_text("video")
        (doc_dir / "readme.txt").write_text("text")
        (doc_dir / "cover.jpg").write_bytes(b"image")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True, scan_all=True)

        assert count == 1
        assert any("Planet" in str(p) for p, _, _ in service._file_index)

    def test_build_file_index_scan_all_skips_symlinks(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """scan_all=True ignore les symlinks dans storage."""
        storage = tmp_path / "storage"
        storage.mkdir()

        doc_dir = storage / "Documentaire"
        doc_dir.mkdir()
        real_file = doc_dir / "Planet Earth (2006).mkv"
        real_file.write_text("video")
        (doc_dir / "Planet Earth Link.mkv").symlink_to(real_file)

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True, scan_all=True)

        # Seul le fichier réel est indexé, pas le symlink
        assert count == 1

    def test_build_file_index_scan_all_with_subdirectories(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """scan_all=True scanne récursivement les sous-répertoires."""
        storage = tmp_path / "storage"
        storage.mkdir()

        # Structure : Documentaire/Science/sous-dossier/
        deep_dir = storage / "Documentaire" / "Science" / "Espace"
        deep_dir.mkdir(parents=True)
        (deep_dir / "Cosmos (2014).mkv").write_text("video")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True, scan_all=True)

        assert count == 1
        assert any("Cosmos" in str(p) for p, _, _ in service._file_index)

    def test_build_file_index_fallback_without_films_series(
        self, mock_file_system, mock_video_file_repo, tmp_path
    ):
        """Sans Films/Séries et sans scan_all, fallback sur storage_dir complet."""
        storage = tmp_path / "storage"
        storage.mkdir()

        # Pas de Films ni Séries
        doc_dir = storage / "Documentaire"
        doc_dir.mkdir()
        (doc_dir / "Planet Earth (2006).mkv").write_text("video")

        service = RepairService(
            file_system=mock_file_system,
            video_file_repo=mock_video_file_repo,
            storage_dir=storage,
            video_dir=tmp_path / "video",
        )

        count = service.build_file_index(force_rebuild=True)

        # Fallback: scanne tout storage_dir
        assert count == 1


    def test_issue_to_dict(self):
        """IntegrityIssue.to_dict() retourne un dict serialisable."""
        issue = IntegrityIssue(
            type=IssueType.GHOST_ENTRY,
            path=Path("/test/path.mkv"),
            details="test details",
        )

        d = issue.to_dict()

        assert d["type"] == "ghost_entry"
        assert d["path"] == "/test/path.mkv"
        assert d["details"] == "test details"

    def test_repair_action_to_dict(self):
        """RepairAction.to_dict() retourne un dict serialisable."""
        action = RepairAction(
            link=Path("/video/test.mkv"),
            action=RepairActionType.REPAIRED,
            new_target=Path("/storage/test.mkv"),
        )

        d = action.to_dict()

        assert d["link"] == "/video/test.mkv"
        assert d["action"] == "repaired"
        assert d["new_target"] == "/storage/test.mkv"
        assert "timestamp" in d
