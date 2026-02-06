"""
Tests TDD pour CleanupService - nettoyage et reorganisation du repertoire video.

TDD tests couvrant:
- Dataclasses (CleanupReport, SubdivisionPlan, etc.)
- Methodes repository (get_by_symlink_path, update_symlink_path)
- Analyse (scan broken, empty dirs, oversized dirs, misplaced symlinks)
- Execution (repair, fix misplaced, subdivide, clean empty)
- Algorithme de subdivision
- Commande CLI (dry-run, --fix)
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.entities.media import Movie, Series, Episode
from src.core.entities.video import VideoFile
from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupReport,
    CleanupResult,
    CleanupService,
    CleanupStepType,
    MisplacedSymlink,
    SubdivisionPlan,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_repair_service():
    """Mock du RepairService."""
    service = MagicMock()
    service.find_broken_symlinks = MagicMock(return_value=[])
    service.find_possible_targets = MagicMock(return_value=[])
    service.repair_symlink = MagicMock(return_value=True)
    service.build_file_index = MagicMock(return_value=100)
    return service


@pytest.fixture
def mock_organizer_service():
    """Mock du OrganizerService."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_video_file_repo():
    """Mock du IVideoFileRepository."""
    repo = MagicMock()
    repo.get_by_symlink_path = MagicMock(return_value=None)
    repo.get_by_path = MagicMock(return_value=None)
    repo.update_symlink_path = MagicMock(return_value=True)
    mock_session = MagicMock()
    mock_session.exec.return_value.first.return_value = None
    repo._session = mock_session
    return repo


@pytest.fixture
def mock_movie_repo():
    """Mock du IMovieRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def mock_series_repo():
    """Mock du ISeriesRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def mock_episode_repo():
    """Mock du IEpisodeRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def temp_dirs(tmp_path):
    """Cree les repertoires temporaires pour les tests."""
    video_dir = tmp_path / "video"
    video_dir.mkdir()
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    return {"video": video_dir, "storage": storage_dir}


@pytest.fixture
def cleanup_service(
    mock_repair_service,
    mock_organizer_service,
    mock_video_file_repo,
    mock_movie_repo,
    mock_series_repo,
    mock_episode_repo,
):
    """Cree un CleanupService avec des mocks."""
    return CleanupService(
        repair_service=mock_repair_service,
        organizer_service=mock_organizer_service,
        video_file_repo=mock_video_file_repo,
        movie_repo=mock_movie_repo,
        series_repo=mock_series_repo,
        episode_repo=mock_episode_repo,
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


# ============================================================================
# Phase 2 : Repository
# ============================================================================


class TestRepositoryMethods:
    """Tests pour les methodes get_by_symlink_path et update_symlink_path."""

    def test_get_by_symlink_path_found(self):
        """get_by_symlink_path retourne le VideoFile quand il existe."""
        from sqlmodel import Session, SQLModel, create_engine, select
        from src.infrastructure.persistence.models import VideoFileModel
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            model = VideoFileModel(
                path="/storage/film.mkv",
                symlink_path="/video/Films/Action/film.mkv",
                filename="film.mkv",
                size_bytes=1000,
            )
            session.add(model)
            session.commit()

            repo = SQLModelVideoFileRepository(session)
            result = repo.get_by_symlink_path(Path("/video/Films/Action/film.mkv"))

            assert result is not None
            assert result.filename == "film.mkv"
            assert result.symlink_path == Path("/video/Films/Action/film.mkv")

    def test_get_by_symlink_path_not_found(self):
        """get_by_symlink_path retourne None quand inexistant."""
        from sqlmodel import Session, SQLModel, create_engine
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            repo = SQLModelVideoFileRepository(session)
            result = repo.get_by_symlink_path(Path("/video/Films/inexistant.mkv"))

            assert result is None

    def test_update_symlink_path(self):
        """update_symlink_path met a jour le chemin en BDD."""
        from sqlmodel import Session, SQLModel, create_engine, select
        from src.infrastructure.persistence.models import VideoFileModel
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            model = VideoFileModel(
                path="/storage/film.mkv",
                symlink_path="/video/Films/Drame/film.mkv",
                filename="film.mkv",
                size_bytes=1000,
            )
            session.add(model)
            session.commit()

            repo = SQLModelVideoFileRepository(session)
            result = repo.update_symlink_path(
                Path("/video/Films/Drame/film.mkv"),
                Path("/video/Films/Action/film.mkv"),
            )

            assert result is True

            # Verifier en BDD
            updated = session.exec(
                select(VideoFileModel).where(VideoFileModel.id == model.id)
            ).first()
            assert updated.symlink_path == "/video/Films/Action/film.mkv"

    def test_update_symlink_path_not_found(self):
        """update_symlink_path retourne False si le chemin n'existe pas."""
        from sqlmodel import Session, SQLModel, create_engine
        from src.infrastructure.persistence.repositories.video_file_repository import (
            SQLModelVideoFileRepository,
        )

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            repo = SQLModelVideoFileRepository(session)
            result = repo.update_symlink_path(
                Path("/video/inexistant.mkv"),
                Path("/video/nouveau.mkv"),
            )
            assert result is False


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
    """Tests pour _scan_oversized_dirs."""

    def test_scan_oversized_dirs(self, cleanup_service, temp_dirs):
        """Detecte les repertoires avec plus de 50 fichiers."""
        video_dir = temp_dirs["video"]
        genre_dir = video_dir / "Films" / "Action"
        genre_dir.mkdir(parents=True)

        # Creer 55 symlinks
        for i in range(55):
            link = genre_dir / f"Film {i:03d} (2020).mkv"
            link.symlink_to(f"/storage/film{i}.mkv")

        result = cleanup_service._scan_oversized_dirs(video_dir, max_files=50)

        assert len(result) == 1
        assert result[0].parent_dir == genre_dir
        assert result[0].current_count == 55
        assert result[0].max_allowed == 50


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


# ============================================================================
# Phase 5 : Subdivision
# ============================================================================


class TestCalculateSubdivisionRanges:
    """Tests pour _calculate_subdivision_ranges."""

    def test_calculate_ranges_60_items(self, cleanup_service, tmp_path):
        """60 items -> 2 plages (50+10)."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Creer 60 symlinks avec des noms tries
        names = []
        for i in range(60):
            letter = chr(ord("A") + (i // 3))  # A, A, A, B, B, B, ...
            suffix = chr(ord("a") + (i % 3))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            names.append(name)

        for name in sorted(names):
            link = parent / name
            link.symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert plan.parent_dir == parent
        assert plan.current_count == 60
        assert len(plan.ranges) == 2
        assert len(plan.items_to_move) == 60

    def test_calculate_ranges_with_articles(self, cleanup_service, tmp_path):
        """'Le Parrain' trie sous P, pas sous L."""
        parent = tmp_path / "Films" / "Drame"
        parent.mkdir(parents=True)

        # Creer quelques symlinks dont un avec article
        (parent / "Le Parrain (1972).mkv").symlink_to("/storage/parrain.mkv")
        (parent / "Alien (1979).mkv").symlink_to("/storage/alien.mkv")
        (parent / "Blade Runner (1982).mkv").symlink_to("/storage/blade.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=2)

        # Verifier que "Le Parrain" est trie sous P
        # Alien (A), Blade Runner (B) dans le premier groupe
        # Le Parrain (P) dans le deuxieme groupe
        assert len(plan.ranges) == 2

        # Trouver le mouvement pour Le Parrain
        parrain_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Le Parrain" in src.name
        ]
        assert len(parrain_moves) == 1
        # Le Parrain devrait etre dans un repertoire different de Alien/Blade Runner
        alien_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Alien" in src.name
        ]
        assert parrain_moves[0][1].parent != alien_moves[0][1].parent

    def test_subdivide_creates_dirs_and_moves(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs cree les sous-repertoires et deplace."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Creer des symlinks
        link1 = parent / "Alpha (2020).mkv"
        link1.symlink_to("/storage/alpha.mkv")
        link2 = parent / "Zeta (2020).mkv"
        link2.symlink_to("/storage/zeta.mkv")

        dest_a = parent / "Al-Al"
        dest_z = parent / "Ze-Ze"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=2,
                max_allowed=1,
                ranges=[("Al", "Al"), ("Ze", "Ze")],
                items_to_move=[
                    (link1, dest_a / "Alpha (2020).mkv"),
                    (link2, dest_z / "Zeta (2020).mkv"),
                ],
            ),
        ]

        result = cleanup_service.subdivide_oversized_dirs(plans)

        assert result.subdivisions_created == 1
        assert result.symlinks_redistributed == 2
        assert (dest_a / "Alpha (2020).mkv").is_symlink()
        assert (dest_z / "Zeta (2020).mkv").is_symlink()

    def test_subdivide_updates_db(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs met a jour symlink_path en BDD."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        link = parent / "Film (2020).mkv"
        link.symlink_to("/storage/film.mkv")

        dest = parent / "Fi-Fi"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=1,
                max_allowed=1,
                ranges=[("Fi", "Fi")],
                items_to_move=[
                    (link, dest / "Film (2020).mkv"),
                ],
            ),
        ]

        cleanup_service.subdivide_oversized_dirs(plans)

        mock_video_file_repo.update_symlink_path.assert_called_once_with(
            link, dest / "Film (2020).mkv",
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
        with patch("src.adapters.cli.commands.Container") as MockContainer:
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

        with patch("src.adapters.cli.commands.Container") as MockContainer:
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
                )
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
            mock_cleanup_svc.fix_misplaced_symlinks.return_value = CleanupResult()
            mock_cleanup_svc.subdivide_oversized_dirs.return_value = CleanupResult()
            mock_cleanup_svc.clean_empty_dirs.return_value = CleanupResult(
                empty_dirs_removed=1,
            )
            mock_container.cleanup_service.return_value = mock_cleanup_svc

            from src.main import app
            result = runner.invoke(app, ["cleanup", "--fix"])

            mock_cleanup_svc.repair_broken_symlinks.assert_called_once()
            mock_cleanup_svc.clean_empty_dirs.assert_called_once()
