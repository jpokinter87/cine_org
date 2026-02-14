"""
Service d'orchestration du workflow complet de traitement des videos.

Ce service coordonne les etapes du workflow de traitement :
- Nettoyage des orphelins
- Scan des telechargements
- Matching avec les APIs
- Auto-validation
- Validation manuelle (interactive)
- Batch transfer
- Resume final
"""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from rich.console import Console

from .dataclasses import WorkflowConfig, WorkflowResult, WorkflowState
from .matching_step import MatchingStepMixin
from .scan_step import ScanStepMixin
from .transfer_step import TransferStepMixin

if TYPE_CHECKING:
    from src.adapters.api.tmdb_client import TMDBClient
    from src.adapters.api.tvdb_client import TVDBClient
    from src.container import Container
    from src.services.matcher import MatcherService
    from src.services.organizer import OrganizerService
    from src.services.renamer import RenamerService
    from src.services.scanner import ScannerService
    from src.services.transferer import TransfererService
    from src.services.validation import ValidationService


class WorkflowService(ScanStepMixin, MatchingStepMixin, TransferStepMixin):
    """
    Service d'orchestration du workflow complet.

    Ce service coordonne les differentes etapes du traitement des videos,
    de l'initialisation au nettoyage final.

    Utilisation typique:
        workflow = WorkflowService(container)
        result = await workflow.execute(WorkflowConfig(dry_run=True))
    """

    def __init__(
        self,
        container: "Container",
        console: Optional[Console] = None,
        scanner: Optional["ScannerService"] = None,
        validation_service: Optional["ValidationService"] = None,
        matcher: Optional["MatcherService"] = None,
        tmdb_client: Optional["TMDBClient"] = None,
        tvdb_client: Optional["TVDBClient"] = None,
        renamer: Optional["RenamerService"] = None,
        organizer: Optional["OrganizerService"] = None,
        transferer: Optional["TransfererService"] = None,
    ) -> None:
        """
        Initialise le service de workflow.

        Args:
            container: Container d'injection de dependances
            console: Console Rich pour les affichages (creee si None)
            scanner: ScannerService (optionnel, pour les tests)
            validation_service: ValidationService (optionnel, pour les tests)
            matcher: MatcherService (optionnel, pour les tests)
            tmdb_client: TMDBClient (optionnel, pour les tests)
            tvdb_client: TVDBClient (optionnel, pour les tests)
            renamer: RenamerService (optionnel, pour les tests)
            organizer: OrganizerService (optionnel, pour les tests)
            transferer: TransfererService (optionnel, pour les tests)
        """
        self._container = container
        self._console = console or Console()

        # Services (recuperes depuis le container ou injectes)
        self._scanner = scanner
        self._validation_service = validation_service
        self._matcher = matcher
        self._tmdb_client = tmdb_client
        self._tvdb_client = tvdb_client
        self._renamer = renamer
        self._organizer = organizer
        self._transferer = transferer

    async def execute(self, config: WorkflowConfig) -> WorkflowResult:
        """
        Execute le workflow complet avec la configuration donnee.

        Args:
            config: Configuration du workflow

        Returns:
            WorkflowResult avec l'etat final et les erreurs eventuelles
        """
        # Initialiser les services
        self._initialize_services(config)

        # Initialiser l'etat
        state = WorkflowState()

        try:
            # Etape 1: Nettoyage des orphelins
            await self._cleanup_orphans(state)

            # Etape 2: Scan des telechargements
            await self._scan_downloads(config, state)

            if not state.scan_results:
                self._console.print("[yellow]Aucun fichier à traiter.[/yellow]")
                return WorkflowResult(success=True, state=state)

            # Etape 3: Matching avec les APIs
            await self._perform_matching(state)

            # Etape 4: Auto-validation
            await self._auto_validate(state)

            # Etape 5: Validation manuelle (si pas dry-run)
            if not config.dry_run:
                await self._manual_validate(state)

            # Etape 6: Batch transfer ou affichage dry-run
            await self._batch_transfer(config, state)

            # Etape 7: Resume final
            self._print_summary(state)

            # Etape 8: Nettoyage dry-run
            if config.dry_run:
                await self._cleanup_dry_run(state)

            return WorkflowResult(success=True, state=state)

        except Exception as e:
            logger.exception(f"Erreur lors du workflow: {e}")
            return WorkflowResult(success=False, state=state, errors=[str(e)])

    def _initialize_services(self, config: WorkflowConfig) -> None:
        """Initialise les services necessaires depuis le container ou utilise ceux injectes."""
        if self._scanner is None:
            self._scanner = self._container.scanner_service()
        if self._validation_service is None:
            self._validation_service = self._container.validation_service()
        if self._matcher is None:
            self._matcher = self._container.matcher_service()
        if self._tmdb_client is None:
            self._tmdb_client = self._container.tmdb_client()
        if self._tvdb_client is None:
            self._tvdb_client = self._container.tvdb_client()
        if self._renamer is None:
            self._renamer = self._container.renamer_service()
        if self._organizer is None:
            self._organizer = self._container.organizer_service()
        if self._transferer is None:
            self._transferer = self._container.transferer_service(
                storage_dir=config.storage_dir,
                video_dir=config.video_dir,
            )

    async def _cleanup_orphans(self, state: WorkflowState) -> None:
        """
        Nettoie les enregistrements orphelins des executions precedentes.

        Supprime les PendingValidation et VideoFile qui n'ont pas ete
        transferes (runs precedents interrompus).
        """
        pending_repo = self._container.pending_validation_repository()
        video_file_repo = self._container.video_file_repository()

        orphans = self._validation_service.list_pending() + self._validation_service.list_validated()

        for pv in orphans:
            if pv.id:
                pending_repo.delete(pv.id)
            if pv.video_file and pv.video_file.id:
                video_file_repo.delete(pv.video_file.id)
            state.orphan_count += 1

        if state.orphan_count > 0:
            self._console.print(
                f"[dim]Nettoyage: {state.orphan_count} enregistrement(s) "
                f"orphelin(s) supprimé(s)[/dim]\n"
            )
