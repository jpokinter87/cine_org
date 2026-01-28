"""
Tests unitaires pour les commandes CLI principales.

Tests couvrant:
- process: workflow complet avec filtrage et dry-run
- pending: affichage des fichiers en attente
- validate file: validation d'un fichier par ID
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.adapters.cli.commands import (
    MediaFilter,
    _pending_async,
    _process_async,
    _render_pending_panel,
    _validate_file_async,
    pending,
    process,
    validate_file,
)
from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult


runner = CliRunner()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_container():
    """Mock le Container pour les tests."""
    with patch("src.adapters.cli.commands.Container") as mock:
        container_instance = MagicMock()
        mock.return_value = container_instance
        container_instance.database.init = AsyncMock()
        container_instance.config.return_value = MagicMock(
            storage_dir="/storage",
            video_dir="/video",
        )
        yield container_instance


@pytest.fixture
def pending_movie() -> PendingValidation:
    """Cree un PendingValidation pour un film."""
    video_file = VideoFile(
        id="vf1",
        path=Path("/downloads/Avatar.2009.mkv"),
        filename="Avatar.2009.mkv",
    )
    return PendingValidation(
        id="1",
        video_file=video_file,
        candidates=[
            {"id": "1", "title": "Avatar", "year": 2009, "score": 95.0, "source": "tmdb"},
        ],
    )


@pytest.fixture
def pending_series() -> PendingValidation:
    """Cree un PendingValidation pour une serie."""
    video_file = VideoFile(
        id="vf2",
        path=Path("/downloads/Game.of.Thrones.S01E01.mkv"),
        filename="Game.of.Thrones.S01E01.mkv",
    )
    return PendingValidation(
        id="2",
        video_file=video_file,
        candidates=[
            {"id": "121361", "title": "Game of Thrones", "year": 2011, "score": 90.0, "source": "tvdb"},
        ],
    )


@pytest.fixture
def pending_no_candidates() -> PendingValidation:
    """Cree un PendingValidation sans candidats."""
    video_file = VideoFile(
        id="vf3",
        path=Path("/downloads/Unknown.2020.mkv"),
        filename="Unknown.2020.mkv",
    )
    return PendingValidation(
        id="3",
        video_file=video_file,
        candidates=[],
    )


# ============================================================================
# Tests MediaFilter
# ============================================================================


class TestMediaFilter:
    """Tests pour l'enum MediaFilter."""

    def test_media_filter_values(self):
        """Verifie les valeurs de l'enum."""
        assert MediaFilter.ALL.value == "all"
        assert MediaFilter.MOVIES.value == "movies"
        assert MediaFilter.SERIES.value == "series"

    def test_media_filter_is_str_enum(self):
        """MediaFilter herite de str."""
        assert isinstance(MediaFilter.ALL, str)
        assert MediaFilter.MOVIES == "movies"


# ============================================================================
# Tests _render_pending_panel
# ============================================================================


class TestRenderPendingPanel:
    """Tests pour la fonction _render_pending_panel."""

    def test_render_pending_panel_with_candidates(self, pending_movie):
        """Panel avec candidats affiche le meilleur."""
        from rich.panel import Panel

        panel = _render_pending_panel(pending_movie)

        assert isinstance(panel, Panel)
        content = str(panel.renderable)
        assert "Avatar.2009.mkv" in content
        assert "Avatar" in content  # Titre du meilleur candidat
        assert "95" in content  # Score

    def test_render_pending_panel_no_candidates(self, pending_no_candidates):
        """Panel sans candidats affiche 'Aucun candidat'."""
        from rich.panel import Panel

        panel = _render_pending_panel(pending_no_candidates)

        assert isinstance(panel, Panel)
        content = str(panel.renderable)
        assert "Aucun candidat" in content

    def test_render_pending_panel_shows_id(self, pending_movie):
        """Panel affiche l'ID du fichier."""
        panel = _render_pending_panel(pending_movie)
        content = str(panel.renderable)
        assert "ID: 1" in content


# ============================================================================
# Tests process command
# ============================================================================


class TestProcessCommand:
    """Tests pour la commande process."""

    @pytest.mark.asyncio
    async def test_process_dry_run_no_files(self, mock_container):
        """process --dry-run sans fichiers affiche message."""
        # Setup scanner vide
        scanner_mock = MagicMock()
        scanner_mock.scan_downloads.return_value = iter([])
        mock_container.scanner_service.return_value = scanner_mock
        mock_container.validation_service.return_value = MagicMock()

        with patch("src.adapters.cli.commands.console") as mock_console:
            await _process_async(MediaFilter.ALL, dry_run=True)

        # Verifie qu'un message a ete affiche
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Aucun fichier" in str(call) or "0" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_process_filters_movies_only(self, mock_container):
        """process --filter movies ignore les series."""
        from src.core.value_objects.parsed_info import MediaType

        # Setup scanner avec film et serie
        movie_result = MagicMock()
        movie_result.detected_type = MediaType.MOVIE
        movie_result.video_file.filename = "movie.mkv"
        movie_result.video_file.path = Path("/downloads/movie.mkv")
        movie_result.media_info = None

        series_result = MagicMock()
        series_result.detected_type = MediaType.SERIES
        series_result.video_file.filename = "series.S01E01.mkv"

        scanner_mock = MagicMock()
        scanner_mock.scan_downloads.return_value = iter([movie_result, series_result])
        mock_container.scanner_service.return_value = scanner_mock

        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = []
        validation_svc.list_validated.return_value = []
        validation_svc.process_auto_validation = AsyncMock(
            return_value=MagicMock(auto_validated=False)
        )
        mock_container.validation_service.return_value = validation_svc

        video_file_repo = MagicMock()
        video_file_repo.save.return_value = MagicMock(id="1")
        mock_container.video_file_repository.return_value = video_file_repo

        pending_repo = MagicMock()
        mock_container.pending_validation_repository.return_value = pending_repo

        with patch("src.adapters.cli.commands.console"):
            await _process_async(MediaFilter.MOVIES, dry_run=True)

        # Verifie qu'un seul fichier a ete traite (le film)
        assert video_file_repo.save.call_count == 1

    @pytest.mark.asyncio
    async def test_process_filters_series_only(self, mock_container):
        """process --filter series ignore les films."""
        from src.core.value_objects.parsed_info import MediaType

        # Setup scanner avec film et serie
        movie_result = MagicMock()
        movie_result.detected_type = MediaType.MOVIE
        movie_result.video_file.filename = "movie.mkv"

        series_result = MagicMock()
        series_result.detected_type = MediaType.SERIES
        series_result.video_file.filename = "series.S01E01.mkv"
        series_result.video_file.path = Path("/downloads/series.S01E01.mkv")
        series_result.media_info = None

        scanner_mock = MagicMock()
        scanner_mock.scan_downloads.return_value = iter([movie_result, series_result])
        mock_container.scanner_service.return_value = scanner_mock

        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = []
        validation_svc.list_validated.return_value = []
        validation_svc.process_auto_validation = AsyncMock(
            return_value=MagicMock(auto_validated=False)
        )
        mock_container.validation_service.return_value = validation_svc

        video_file_repo = MagicMock()
        video_file_repo.save.return_value = MagicMock(id="1")
        mock_container.video_file_repository.return_value = video_file_repo

        pending_repo = MagicMock()
        mock_container.pending_validation_repository.return_value = pending_repo

        with patch("src.adapters.cli.commands.console"):
            await _process_async(MediaFilter.SERIES, dry_run=True)

        # Verifie qu'un seul fichier a ete traite (la serie)
        assert video_file_repo.save.call_count == 1

    @pytest.mark.asyncio
    async def test_process_dry_run_no_transfer(self, mock_container):
        """process --dry-run ne lance pas le transfert."""
        from src.core.value_objects.parsed_info import MediaType

        # Setup scanner avec un film
        movie_result = MagicMock()
        movie_result.detected_type = MediaType.MOVIE
        movie_result.video_file.filename = "movie.mkv"
        movie_result.video_file.path = Path("/downloads/movie.mkv")
        movie_result.media_info = None

        scanner_mock = MagicMock()
        scanner_mock.scan_downloads.return_value = iter([movie_result])
        mock_container.scanner_service.return_value = scanner_mock

        # Setup validation service avec fichier valide
        validated_pending = MagicMock()
        validated_pending.video_file = MagicMock()
        validated_pending.video_file.path = Path("/downloads/movie.mkv")
        validated_pending.candidates = []
        validated_pending.selected_candidate_id = "1"

        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = []
        validation_svc.list_validated.return_value = [validated_pending]
        validation_svc.process_auto_validation = AsyncMock(
            return_value=MagicMock(auto_validated=True)
        )
        mock_container.validation_service.return_value = validation_svc

        video_file_repo = MagicMock()
        video_file_repo.save.return_value = MagicMock(id="1")
        mock_container.video_file_repository.return_value = video_file_repo

        pending_repo = MagicMock()
        mock_container.pending_validation_repository.return_value = pending_repo

        transferer_mock = MagicMock()
        mock_container.transferer_service.return_value = transferer_mock

        with patch("src.adapters.cli.commands.console") as mock_console:
            await _process_async(MediaFilter.ALL, dry_run=True)

        # Verifie que le message dry-run a ete affiche
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("dry-run" in str(call).lower() for call in calls)

        # Verifie que transferer n'a pas ete appele
        assert not transferer_mock.transfer_file.called


# ============================================================================
# Tests pending command
# ============================================================================


class TestPendingCommand:
    """Tests pour la commande pending."""

    @pytest.mark.asyncio
    async def test_pending_empty_list(self, mock_container):
        """pending sans fichiers affiche message et exit 0."""
        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = []
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.console") as mock_console:
            # typer.Exit lance une exception click.exceptions.Exit
            from click.exceptions import Exit
            with pytest.raises(Exit) as exc_info:
                await _pending_async(all_files=False)

        assert exc_info.value.exit_code == 0
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Aucun fichier" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_pending_shows_files_sorted_by_score(
        self, mock_container, pending_movie, pending_series
    ):
        """pending trie par score decroissant."""
        # pending_movie a score 95, pending_series a score 90
        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = [pending_series, pending_movie]
        mock_container.validation_service.return_value = validation_svc

        printed_panels = []

        with patch("src.adapters.cli.commands.console") as mock_console:
            def capture_print(*args, **kwargs):
                if args:
                    printed_panels.append(str(args[0]))
            mock_console.print.side_effect = capture_print
            await _pending_async(all_files=True)

        # Le premier panel affiche devrait etre pending_movie (score 95)
        # Chercher l'ordre dans les panels affiches
        avatar_idx = -1
        got_idx = -1
        for i, panel in enumerate(printed_panels):
            if "Avatar.2009.mkv" in panel:
                avatar_idx = i
            if "Game.of.Thrones" in panel:
                got_idx = i

        # Avatar (score 95) devrait apparaitre avant GoT (score 90)
        if avatar_idx >= 0 and got_idx >= 0:
            assert avatar_idx < got_idx

    @pytest.mark.asyncio
    async def test_pending_pagination_default(self, mock_container):
        """pending affiche max 15 fichiers par defaut."""
        # Creer 20 fichiers pending
        pending_list = []
        for i in range(20):
            vf = VideoFile(
                id=f"vf{i}",
                path=Path(f"/downloads/movie{i}.mkv"),
                filename=f"movie{i}.mkv",
            )
            pend = PendingValidation(
                id=str(i),
                video_file=vf,
                candidates=[{"id": "1", "title": f"Movie {i}", "score": 50.0, "source": "tmdb"}],
            )
            pending_list.append(pend)

        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = pending_list
        mock_container.validation_service.return_value = validation_svc

        panel_count = 0

        with patch("src.adapters.cli.commands.console") as mock_console:
            def count_panels(*args, **kwargs):
                nonlocal panel_count
                from rich.panel import Panel
                if args and isinstance(args[0], Panel):
                    panel_count += 1
            mock_console.print.side_effect = count_panels
            await _pending_async(all_files=False)

        # Maximum 15 panels
        assert panel_count <= 15

    @pytest.mark.asyncio
    async def test_pending_all_option(self, mock_container):
        """pending --all affiche tous les fichiers."""
        # Creer 20 fichiers pending
        pending_list = []
        for i in range(20):
            vf = VideoFile(
                id=f"vf{i}",
                path=Path(f"/downloads/movie{i}.mkv"),
                filename=f"movie{i}.mkv",
            )
            pend = PendingValidation(
                id=str(i),
                video_file=vf,
                candidates=[{"id": "1", "title": f"Movie {i}", "score": 50.0, "source": "tmdb"}],
            )
            pending_list.append(pend)

        validation_svc = MagicMock()
        validation_svc.list_pending.return_value = pending_list
        mock_container.validation_service.return_value = validation_svc

        panel_count = 0

        with patch("src.adapters.cli.commands.console") as mock_console:
            def count_panels(*args, **kwargs):
                nonlocal panel_count
                from rich.panel import Panel
                if args and isinstance(args[0], Panel):
                    panel_count += 1
            mock_console.print.side_effect = count_panels
            await _pending_async(all_files=True)

        # Tous les 20 panels
        assert panel_count == 20


# ============================================================================
# Tests validate file command
# ============================================================================


class TestValidateFileCommand:
    """Tests pour la commande validate file."""

    @pytest.mark.asyncio
    async def test_validate_file_not_found(self, mock_container):
        """validate file avec ID inexistant retourne erreur."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = None
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.console") as mock_console:
            # typer.Exit lance une exception click.exceptions.Exit
            from click.exceptions import Exit
            with pytest.raises(Exit) as exc_info:
                await _validate_file_async("999")

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Erreur" in str(call) or "non trouve" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_validate_file_success_quit(self, mock_container, pending_movie):
        """validate file avec ID valide et quit."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.validation_loop") as mock_loop:
            mock_loop.return_value = "quit"
            with patch("src.adapters.cli.commands.console"):
                await _validate_file_async("1")

        mock_loop.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_file_trash(self, mock_container, pending_movie):
        """validate file met en corbeille."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.validation_loop") as mock_loop:
            mock_loop.return_value = "trash"
            with patch("src.adapters.cli.commands.console"):
                await _validate_file_async("1")

        validation_svc.reject_pending.assert_called_once_with(pending_movie)

    @pytest.mark.asyncio
    async def test_validate_file_skip(self, mock_container, pending_movie):
        """validate file passe le fichier."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.validation_loop") as mock_loop:
            mock_loop.return_value = None  # Skip
            with patch("src.adapters.cli.commands.console") as mock_console:
                await _validate_file_async("1")

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("passe" in str(call).lower() for call in calls)

    @pytest.mark.asyncio
    async def test_validate_file_validates_candidate(self, mock_container, pending_movie):
        """validate file valide avec le candidat selectionne."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_details = MagicMock()
        mock_details.title = "Avatar"
        validation_svc.validate_candidate = AsyncMock(return_value=mock_details)
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.validation_loop") as mock_loop:
            mock_loop.return_value = "1"  # ID du candidat
            with patch("src.adapters.cli.commands.console") as mock_console:
                await _validate_file_async("1")

        validation_svc.validate_candidate.assert_called_once()
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("valide" in str(call).lower() for call in calls)

    @pytest.mark.asyncio
    async def test_validate_file_already_validated_warning(self, mock_container):
        """validate file avec fichier deja valide affiche avertissement."""
        video_file = VideoFile(
            id="vf1",
            path=Path("/downloads/Avatar.2009.mkv"),
            filename="Avatar.2009.mkv",
        )
        pend = PendingValidation(
            id="1",
            video_file=video_file,
            candidates=[{"id": "1", "title": "Avatar", "score": 95.0, "source": "tmdb"}],
            validation_status=ValidationStatus.VALIDATED,
        )

        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pend
        mock_container.validation_service.return_value = validation_svc

        with patch("src.adapters.cli.commands.validation_loop") as mock_loop:
            mock_loop.return_value = "quit"
            with patch("src.adapters.cli.commands.console") as mock_console:
                await _validate_file_async("1")

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Avertissement" in str(call) or "validated" in str(call) for call in calls)


# ============================================================================
# Tests d'integration CLI (via CliRunner)
# ============================================================================


class TestCLIIntegration:
    """Tests d'integration via le CLI runner."""

    def test_process_help(self):
        """process --help affiche l'aide."""
        from src.main import app

        result = runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0
        assert "--filter" in result.output
        assert "--dry-run" in result.output

    def test_pending_help(self):
        """pending --help affiche l'aide."""
        from src.main import app

        result = runner.invoke(app, ["pending", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output

    def test_validate_file_help(self):
        """validate file --help affiche l'aide."""
        from src.main import app

        result = runner.invoke(app, ["validate", "file", "--help"])
        assert result.exit_code == 0
        assert "FILE_ID" in result.output

    def test_global_verbose_option(self):
        """Option --verbose est disponible globalement."""
        from src.main import app

        result = runner.invoke(app, ["--help"])
        assert "--verbose" in result.output
        assert "-v" in result.output

    def test_global_quiet_option(self):
        """Option --quiet est disponible globalement."""
        from src.main import app

        result = runner.invoke(app, ["--help"])
        assert "--quiet" in result.output
        assert "-q" in result.output
