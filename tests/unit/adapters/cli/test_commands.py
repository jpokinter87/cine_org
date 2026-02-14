"""
Tests unitaires pour les commandes CLI principales.

Tests couvrant:
- process: workflow complet avec filtrage et dry-run
- pending: affichage des fichiers en attente
- import: import de videotheque existante
- validate file: validation d'un fichier par ID
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.adapters.cli.commands import (
    MediaFilter,
    import_library,
    pending,
    process,
    validate_file,
)
from src.adapters.cli.commands.import_commands import _import_library_async
from src.adapters.cli.commands.validate_commands import _validate_file_async
from src.adapters.cli.commands.workflow_commands import (
    _pending_async,
    _process_async,
    _render_pending_panel,
)
from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult

# Chemins de patch pour les sous-modules refactores
_WORKFLOW = "src.adapters.cli.commands.workflow_commands"
_VALIDATE = "src.adapters.cli.commands.validate_commands"
_IMPORT = "src.adapters.cli.commands.import_commands"

runner = CliRunner()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_container():
    """Mock le Container pour les tests.

    Patche Container dans helpers.py car c'est la que le decorateur
    @with_container() l'importe et l'instancie.
    """
    with patch("src.adapters.cli.helpers.Container") as mock_cls:
        container_instance = MagicMock()
        mock_cls.return_value = container_instance
        container_instance.database.init = MagicMock()
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

    @pytest.mark.asyncio
    async def test_process_dry_run_no_files(self, mock_container):
        """process avec dry_run et aucun fichier."""
        mock_container.validation_service.return_value = MagicMock()

        with patch(f"{_WORKFLOW}.console") as mock_console:
            await _process_async(MediaFilter.ALL, dry_run=True)

        # Verifie qu'un message a ete affiche
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Aucun fichier" in str(call) or "0" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_process_filters_movies_only(self, mock_container):
        """process --filter movies ignore les series."""
        from src.core.value_objects.parsed_info import MediaType
        from src.services.workflow import WorkflowResult, WorkflowState

        # Mock WorkflowService directement car il est instancie dans _process_async
        workflow_mock = MagicMock()
        workflow_result = WorkflowResult(
            success=True,
            state=WorkflowState(
                scan_results=[MagicMock(detected_type=MediaType.MOVIE)],
                auto_validated_count=1,
            ),
        )
        workflow_mock.execute = AsyncMock(return_value=workflow_result)

        with patch(f"{_WORKFLOW}.console"), \
             patch("src.services.workflow.WorkflowService", return_value=workflow_mock):
            await _process_async(MediaFilter.MOVIES, dry_run=True)

        # Verifie que le workflow a ete execute avec le bon filtre
        workflow_mock.execute.assert_called_once()
        call_args = workflow_mock.execute.call_args
        assert call_args[0][0].filter_type == "movies"  # WorkflowConfig.filter_type

    @pytest.mark.asyncio
    async def test_process_filters_series_only(self, mock_container):
        """process --filter series ignore les films."""
        from src.core.value_objects.parsed_info import MediaType
        from src.services.workflow import WorkflowResult, WorkflowState

        # Mock WorkflowService directement car il est instancie dans _process_async
        workflow_mock = MagicMock()
        workflow_result = WorkflowResult(
            success=True,
            state=WorkflowState(
                scan_results=[MagicMock(detected_type=MediaType.SERIES)],
                auto_validated_count=1,
            ),
        )
        workflow_mock.execute = AsyncMock(return_value=workflow_result)

        with patch(f"{_WORKFLOW}.console"), \
             patch("src.services.workflow.WorkflowService", return_value=workflow_mock):
            await _process_async(MediaFilter.SERIES, dry_run=True)

        # Verifie que le workflow a ete execute avec le bon filtre
        workflow_mock.execute.assert_called_once()
        call_args = workflow_mock.execute.call_args
        assert call_args[0][0].filter_type == "series"  # WorkflowConfig.filter_type

    @pytest.mark.asyncio
    async def test_process_dry_run_no_transfer(self, mock_container):
        """process --dry-run ne lance pas le transfert."""
        from src.services.workflow import WorkflowResult, WorkflowState

        # Mock WorkflowService directement car il est instancie dans _process_async
        workflow_mock = MagicMock()
        workflow_result = WorkflowResult(
            success=True,
            state=WorkflowState(
                scan_results=[MagicMock()],
                auto_validated_count=1,
            ),
        )
        workflow_mock.execute = AsyncMock(return_value=workflow_result)

        with patch(f"{_WORKFLOW}.console") as mock_console, \
             patch("src.services.workflow.WorkflowService", return_value=workflow_mock):
            await _process_async(MediaFilter.ALL, dry_run=True)

        # Verifie que le workflow a ete execute en mode dry-run
        workflow_mock.execute.assert_called_once()
        call_args = workflow_mock.execute.call_args
        assert call_args[0][0].dry_run is True  # WorkflowConfig.dry_run



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

        with patch(f"{_WORKFLOW}.console") as mock_console:
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

        with patch(f"{_WORKFLOW}.console") as mock_console:
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

        with patch(f"{_WORKFLOW}.console") as mock_console:
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

        with patch(f"{_WORKFLOW}.console") as mock_console:
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

        with patch(f"{_VALIDATE}.console") as mock_console:
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

        with patch(f"{_VALIDATE}.validation_loop") as mock_loop:
            mock_loop.return_value = "quit"
            with patch(f"{_VALIDATE}.console"):
                await _validate_file_async("1")

        mock_loop.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_file_trash(self, mock_container, pending_movie):
        """validate file met en corbeille."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_container.validation_service.return_value = validation_svc

        with patch(f"{_VALIDATE}.validation_loop") as mock_loop:
            mock_loop.return_value = "trash"
            with patch(f"{_VALIDATE}.console"):
                await _validate_file_async("1")

        validation_svc.reject_pending.assert_called_once_with(pending_movie)

    @pytest.mark.asyncio
    async def test_validate_file_skip(self, mock_container, pending_movie):
        """validate file passe le fichier."""
        validation_svc = MagicMock()
        validation_svc.get_pending_by_id.return_value = pending_movie
        mock_container.validation_service.return_value = validation_svc

        with patch(f"{_VALIDATE}.validation_loop") as mock_loop:
            mock_loop.return_value = None  # Skip
            with patch(f"{_VALIDATE}.console") as mock_console:
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

        with patch(f"{_VALIDATE}.validation_loop") as mock_loop:
            mock_loop.return_value = "1"  # ID du candidat
            with patch(f"{_VALIDATE}.console") as mock_console:
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

        with patch(f"{_VALIDATE}.validation_loop") as mock_loop:
            mock_loop.return_value = "quit"
            with patch(f"{_VALIDATE}.console") as mock_console:
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

    def test_import_help(self):
        """import --help affiche l'aide."""
        from src.main import app

        result = runner.invoke(app, ["import", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--from-symlinks" in result.output
        assert "SOURCE_DIR" in result.output

    def test_import_in_global_help(self):
        """import apparait dans l'aide globale."""
        from src.main import app

        result = runner.invoke(app, ["--help"])
        assert "import" in result.output


# ============================================================================
# Tests import command
# ============================================================================


class TestImportCommand:
    """Tests pour la commande import."""

    @pytest.mark.asyncio
    async def test_import_dry_run_shows_message(self, mock_container, tmp_path):
        """import --dry-run affiche le message dry-run."""
        # Creer un repertoire vide
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        # Mock importer service qui ne retourne rien
        importer_mock = MagicMock()
        importer_mock.scan_library.return_value = iter([])
        mock_container.importer_service.return_value = importer_mock

        with patch(f"{_IMPORT}.console") as mock_console:
            await _import_library_async(storage_dir, dry_run=True, from_symlinks=False)

        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("dry-run" in str(call).lower() for call in calls)

    @pytest.mark.asyncio
    async def test_import_counts_imported_files(self, mock_container, tmp_path):
        """import compte correctement les fichiers importes."""
        from src.services.importer import ImportDecision, ImportResult

        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        # Mock importer service avec 2 fichiers importes
        importer_mock = MagicMock()
        importer_mock.scan_library.return_value = iter([
            ImportResult(filename="film1.mkv", decision=ImportDecision.IMPORT),
            ImportResult(filename="film2.mkv", decision=ImportDecision.IMPORT),
        ])
        mock_container.importer_service.return_value = importer_mock

        with patch(f"{_IMPORT}.console") as mock_console:
            await _import_library_async(storage_dir, dry_run=False, from_symlinks=False)

        calls = [str(call) for call in mock_console.print.call_args_list]
        # Verifier que le resume affiche "2 importe(s)"
        assert any("2" in str(call) and "importe" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_import_counts_skipped_files(self, mock_container, tmp_path):
        """import compte correctement les fichiers ignores."""
        from src.services.importer import ImportDecision, ImportResult

        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        # Mock importer service avec 1 fichier skip
        importer_mock = MagicMock()
        importer_mock.scan_library.return_value = iter([
            ImportResult(filename="film1.mkv", decision=ImportDecision.SKIP_KNOWN),
        ])
        mock_container.importer_service.return_value = importer_mock

        with patch(f"{_IMPORT}.console") as mock_console:
            await _import_library_async(storage_dir, dry_run=False, from_symlinks=False)

        calls = [str(call) for call in mock_console.print.call_args_list]
        # Verifier que le resume affiche "1 ignore(s)"
        assert any("1" in str(call) and "ignore" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_import_counts_errors(self, mock_container, tmp_path):
        """import compte et affiche les erreurs."""
        from src.services.importer import ImportDecision, ImportResult

        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        # Mock importer service avec 1 erreur
        importer_mock = MagicMock()
        importer_mock.scan_library.return_value = iter([
            ImportResult(
                filename="broken.mkv",
                decision=ImportDecision.ERROR,
                error_message="Access denied"
            ),
        ])
        mock_container.importer_service.return_value = importer_mock

        with patch(f"{_IMPORT}.console") as mock_console:
            await _import_library_async(storage_dir, dry_run=False, from_symlinks=False)

        calls = [str(call) for call in mock_console.print.call_args_list]
        # Verifier que le resume affiche "1 erreur(s)"
        assert any("1" in str(call) and "erreur" in str(call) for call in calls)
        # Verifier que l'erreur est affichee
        assert any("Access denied" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_import_nonexistent_directory_fails(self, mock_container):
        """import avec repertoire inexistant retourne erreur."""
        storage_dir = Path("/nonexistent/path/that/does/not/exist")

        with patch(f"{_IMPORT}.console") as mock_console:
            from click.exceptions import Exit
            with pytest.raises(Exit) as exc_info:
                await _import_library_async(storage_dir, dry_run=False, from_symlinks=False)

        assert exc_info.value.exit_code == 1
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Erreur" in str(call) or "introuvable" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_import_uses_config_storage_dir_when_none(self, mock_container, tmp_path):
        """import utilise storage_dir depuis config si non fourni."""
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()

        # Configurer le mock pour retourner notre storage_dir
        mock_container.config.return_value = MagicMock(
            storage_dir=str(storage_dir),
            video_dir="/video",
        )

        importer_mock = MagicMock()
        importer_mock.scan_library.return_value = iter([])
        mock_container.importer_service.return_value = importer_mock

        with patch(f"{_IMPORT}.console"):
            await _import_library_async(None, dry_run=False, from_symlinks=False)

        # Verifier que scan_library a ete appele avec le bon path
        importer_mock.scan_library.assert_called_once()
        called_path = importer_mock.scan_library.call_args[0][0]
        assert str(called_path) == str(storage_dir)
