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
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
    _normalize_sort_key,
    _parse_parent_range,
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

    def test_subdivide_moves_out_of_range_items(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs deplace aussi les items hors plage."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        sibling = grandparent / "G-L"
        sibling.mkdir()

        # Item in-range
        link_in = parent / "Super (2020).mkv"
        link_in.symlink_to("/storage/super.mkv")
        # Item hors-plage
        link_out = parent / "Jadotville (2016).mkv"
        link_out.symlink_to("/storage/jadotville.mkv")

        dest_sub = parent / "Sa-Zz"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=2,
                max_allowed=1,
                ranges=[("Sa", "Zz")],
                items_to_move=[
                    (link_in, dest_sub / "Super (2020).mkv"),
                ],
                out_of_range_items=[
                    (link_out, sibling / "Jadotville (2016).mkv"),
                ],
            ),
        ]

        result = cleanup_service.subdivide_oversized_dirs(plans)

        # L'item in-range est deplace dans la subdivision
        assert (dest_sub / "Super (2020).mkv").is_symlink()
        # L'item hors-plage est deplace vers le frere
        assert (sibling / "Jadotville (2016).mkv").is_symlink()
        assert not link_out.exists()
        # La BDD est mise a jour pour les deux
        assert mock_video_file_repo.update_symlink_path.call_count == 2

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


class TestCleanupCLICache:
    """Tests pour l'utilisation du cache dans la commande CLI."""

    def test_cleanup_dry_run_saves_cache(self, tmp_path):
        """En mode dry-run, le rapport est sauvegarde dans le cache."""
        from typer.testing import CliRunner
        from unittest.mock import patch, MagicMock

        runner = CliRunner()

        with patch("src.adapters.cli.commands.Container") as MockContainer, \
             patch("src.adapters.cli.commands.save_report_cache") as mock_save:
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

        with patch("src.adapters.cli.commands.Container") as MockContainer, \
             patch("src.adapters.cli.commands.load_report_cache") as mock_load, \
             patch("src.adapters.cli.commands.save_report_cache"):
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

        with patch("src.adapters.cli.commands.Container") as MockContainer, \
             patch("src.adapters.cli.commands.load_report_cache") as mock_load, \
             patch("src.adapters.cli.commands.save_report_cache"):
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


# ============================================================================
# Phase 10 : Helpers subdivision (_normalize_sort_key, _parse_parent_range)
# ============================================================================


class TestNormalizeSortKey:
    """Tests pour _normalize_sort_key (suppression des diacritiques)."""

    def test_accent_aigu(self):
        """'Eternel' (accent aigu) -> 'Eternel'."""
        assert _normalize_sort_key("Éternel") == "Eternel"

    def test_accent_grave(self):
        """'A' (accent grave) -> 'A'."""
        assert _normalize_sort_key("À bout de souffle") == "A bout de souffle"

    def test_cedille(self):
        """'Français' (cedille) -> 'Francais'."""
        assert _normalize_sort_key("Français") == "Francais"

    def test_trema(self):
        """'Noël' (trema) -> 'Noel'."""
        assert _normalize_sort_key("Noël") == "Noel"

    def test_ascii_inchange(self):
        """Un texte ASCII reste inchange."""
        assert _normalize_sort_key("Matrix") == "Matrix"


class TestParseParentRange:
    """Tests pour _parse_parent_range (parsing du nom de repertoire en plage)."""

    def test_lettre_simple(self):
        """Lettre simple 'C' -> ('CA', 'CZ')."""
        assert _parse_parent_range("C") == ("CA", "CZ")

    def test_plage_simple(self):
        """Plage 'E-F' -> ('EA', 'FZ')."""
        assert _parse_parent_range("E-F") == ("EA", "FZ")

    def test_plage_large(self):
        """Plage 'S-Z' -> ('SA', 'ZZ')."""
        assert _parse_parent_range("S-Z") == ("SA", "ZZ")

    def test_plage_prefixe(self):
        """Plage avec prefixe 'L-Ma' -> ('LA', 'MA')."""
        assert _parse_parent_range("L-Ma") == ("LA", "MA")

    def test_non_plage(self):
        """Nom de genre 'Action' -> ('AA', 'ZZ') (tout accepter)."""
        assert _parse_parent_range("Action") == ("AA", "ZZ")


# ============================================================================
# Phase 11 : Algorithme de subdivision corrige (7 bugs)
# ============================================================================


class TestSubdivisionAlgorithmBugs:
    """Tests pour les 7 bugs identifies dans _calculate_subdivision_ranges."""

    def test_bug1_balanced_splits(self, cleanup_service, tmp_path):
        """Bug 1 : 59 items -> 2 groupes equilibres (~30+29), pas 50+9."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        for i in range(59):
            letter = chr(ord("A") + (i * 26 // 59))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) == 2
        # Compter les items par plage
        counts = []
        for start, end in plan.ranges:
            label = f"{start}-{end}"
            count = sum(
                1 for _, dst in plan.items_to_move
                if dst.parent.name == label
            )
            counts.append(count)
        # Chaque groupe devrait etre ~29-30, pas 50+9
        assert all(c <= 50 for c in counts)
        assert max(counts) - min(counts) <= 1  # equilibre

    def test_bug2_ranges_cover_parent(self, cleanup_service, tmp_path):
        """Bug 2 : parent S-Z -> premier groupe commence a Sa, dernier finit a Zz."""
        parent = tmp_path / "Films" / "Action" / "S-Z"
        parent.mkdir(parents=True)

        # Creer 55 items dans la plage S-Z
        names = []
        for i, letter in enumerate("STUVWXYZ"):
            for j in range(7):
                suffix = chr(ord("a") + j)
                name = f"{letter}{suffix}_Film_{i*7+j:03d} (2020).mkv"
                names.append(name)
        for name in names[:55]:
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) >= 2
        # Premier groupe commence a Sa
        assert plan.ranges[0][0].upper()[:1] == "S"
        # Dernier groupe finit a Zz
        assert plan.ranges[-1][1].upper()[:1] == "Z"

    def test_bug3_out_of_range_moved_to_sibling(self, cleanup_service, tmp_path):
        """Bug 3 : Jadotville (J) dans S-Z -> deplace vers le repertoire frere J ou contenant J."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        # Creer le repertoire frere qui devrait accueillir Jadotville
        sibling_j = grandparent / "G-L"
        sibling_j.mkdir()

        # Items dans la plage
        for i in range(55):
            letter = chr(ord("S") + (i * 8 // 55))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # Item hors plage (J < S)
        (parent / "Jadotville (2016).mkv").symlink_to("/storage/jadotville.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # Jadotville doit etre dans out_of_range_items avec une destination
        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "Jadotville (2016).mkv" in out_sources

        # La destination doit etre dans le repertoire frere G-L
        jadotville_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Jadotville (2016).mkv"
        ]
        assert len(jadotville_move) == 1
        assert jadotville_move[0][1].parent == sibling_j

        # Jadotville ne doit PAS etre dans items_to_move
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "Jadotville (2016).mkv" not in moved_names

    def test_bug3b_el_chapo_out_of_range_ef(self, cleanup_service, tmp_path):
        """Bug 3b : El Chapo (article 'el' strip -> Chapo=CH) exclu de E-F, deplace vers C-D."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "E-F"
        parent.mkdir(parents=True)
        # Repertoire frere pour C
        sibling_cd = grandparent / "C-D"
        sibling_cd.mkdir()

        # Items dans la plage E-F
        for i in range(55):
            letter = "E" if i < 28 else "F"
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # El Chapo : article "el" strip -> cle "CH", hors plage E-F
        (parent / "El Chapo (2017).mkv").symlink_to("/storage/elchapo.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "El Chapo (2017).mkv" in out_sources
        # Destination dans C-D
        chapo_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "El Chapo (2017).mkv"
        ]
        assert chapo_move[0][1].parent == sibling_cd

    def test_bug3c_das_boot_out_of_range_d(self, cleanup_service, tmp_path):
        """Bug 3c : das Boot (article 'das' strip -> Boot=BO) exclu de D, deplace vers B ou A-C."""
        grandparent = tmp_path / "Films" / "Guerre"
        parent = grandparent / "D"
        parent.mkdir(parents=True)
        # Repertoire frere pour B
        sibling_b = grandparent / "A-C"
        sibling_b.mkdir()

        # Items dans la plage D
        for i in range(55):
            suffix = chr(ord("a") + (i % 26))
            name = f"D{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # das Boot : article "das" strip -> cle "BO", hors plage D
        (parent / "Das Boot (1981).mkv").symlink_to("/storage/dasboot.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "Das Boot (1981).mkv" in out_sources
        # Destination dans A-C
        boot_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Das Boot (1981).mkv"
        ]
        assert boot_move[0][1].parent == sibling_b

    def test_out_of_range_no_sibling_stays_in_grandparent(self, cleanup_service, tmp_path):
        """Si aucun frere ne correspond, l'item va dans le grand-parent."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        # Pas de repertoire frere pour J

        for i in range(55):
            letter = chr(ord("S") + (i * 8 // 55))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        (parent / "Jadotville (2016).mkv").symlink_to("/storage/jadotville.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        jadotville_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Jadotville (2016).mkv"
        ]
        assert len(jadotville_move) == 1
        # Pas de frere -> destination dans le grand-parent
        assert jadotville_move[0][1].parent == grandparent

    def test_bug4_no_overlap(self, cleanup_service, tmp_path):
        """Bug 4 : pas de chevauchement entre plages."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        for i in range(120):
            letter = chr(ord("A") + (i * 26 // 120))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) >= 2
        # Verifier qu'il n'y a pas de chevauchement
        for i in range(len(plan.ranges) - 1):
            end_current = plan.ranges[i][1].upper()
            start_next = plan.ranges[i + 1][0].upper()
            # La fin d'un groupe doit etre strictement avant le debut du suivant
            assert end_current < start_next, (
                f"Chevauchement: {plan.ranges[i]} et {plan.ranges[i+1]}"
            )

    def test_bug5_accents_sorted_correctly(self, cleanup_service, tmp_path):
        """Bug 5 : Eternel (E accent) trie entre D et F, pas apres Z."""
        parent = tmp_path / "Films" / "Drame"
        parent.mkdir(parents=True)

        (parent / "Damien (2020).mkv").symlink_to("/storage/d.mkv")
        (parent / "Éternel (2020).mkv").symlink_to("/storage/e.mkv")
        (parent / "Fatal (2020).mkv").symlink_to("/storage/f.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=2)

        # Eternel doit etre trie entre Damien et Fatal
        eternel_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "ternel" in src.name
        ]
        damien_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Damien" in src.name
        ]
        assert len(eternel_moves) == 1
        assert len(damien_moves) == 1
        # Damien et Eternel devraient etre dans le meme groupe (D et E consecutifs)
        assert damien_moves[0][1].parent == eternel_moves[0][1].parent

    def test_bug6_de_article_stripped(self, cleanup_service, tmp_path):
        """Bug 6 : 'De parfaites demoiselles' dans P-Q -> in-range (cle PA)."""
        parent = tmp_path / "Films" / "Drame" / "P-Q"
        parent.mkdir(parents=True)

        # Items dans la plage P-Q
        for i in range(55):
            letter = "P" if i < 28 else "Q"
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # "De parfaites demoiselles" -> article "de" strip -> "parfaites" -> cle "PA"
        (parent / "De parfaites demoiselles (2020).mkv").symlink_to(
            "/storage/deparfaites.mkv"
        )

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # "De parfaites demoiselles" doit etre in-range (PA est dans P-Q)
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "De parfaites demoiselles (2020).mkv" in moved_names
        # Et pas dans out_of_range
        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "De parfaites demoiselles (2020).mkv" not in out_names

    def test_cb_strike_dots_stripped_in_range_c(self, cleanup_service, tmp_path):
        """C.B. Strike : les points sont ignores, cle 'CB' dans plage C (CA-CZ)."""
        parent = tmp_path / "Séries" / "Séries TV" / "C"
        parent.mkdir(parents=True)

        # Items dans la plage C
        for i in range(52):
            suffix = chr(ord("a") + (i % 26))
            name = f"C{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # C.B. Strike -> sans points -> "CB Strike" -> cle "CB" -> in range
        (parent / "C.B. Strike (2017)").mkdir()

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # C.B. Strike doit etre in-range (pas dans out_of_range)
        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "C.B. Strike (2017)" not in out_names
        # Et present dans items_to_move
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "C.B. Strike (2017)" in moved_names

    def test_au_service_in_range_s(self, cleanup_service, tmp_path):
        """'Au service de la France' : article 'au' strip -> cle 'SE' dans S."""
        parent = tmp_path / "Séries" / "Séries TV" / "S"
        parent.mkdir(parents=True)

        # Items dans la plage S
        for i in range(52):
            suffix = chr(ord("a") + (i % 26))
            name = f"S{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # "Au service de la France" -> strip "au" -> "service de la France"
        # -> strip premier mot seulement -> cle "SE" -> in range S (SA-SZ)
        (parent / "Au service de la France").mkdir()
        (parent / "Au service du passé (2022)").mkdir()

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "Au service de la France" not in out_names
        assert "Au service du passé (2022)" not in out_names
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "Au service de la France" in moved_names
        assert "Au service du passé (2022)" in moved_names

    def test_bug7_always_two_bounds(self, cleanup_service, tmp_path):
        """Bug 7 : toujours format 'Start-End' (jamais borne unique)."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Items tous avec la meme premiere lettre -> pourrait donner "Cr" seul
        for i in range(55):
            suffix = chr(ord("a") + (i % 26))
            name = f"C{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # Chaque plage doit avoir 2 bornes (format Start-End)
        for start, end in plan.ranges:
            assert start != end or len(start) >= 2, (
                f"Borne unique detectee: {start}"
            )
            # Les destinations doivent utiliser le format "Start-End"
            for _, dst in plan.items_to_move:
                dir_name = dst.parent.name
                assert "-" in dir_name, f"Format sans tiret: {dir_name}"
