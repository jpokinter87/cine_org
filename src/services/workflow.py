"""
Service d'orchestration du workflow complet de traitement des vidéos.

Ce service coordonne les étapes du workflow de traitement :
- Nettoyage des orphelins
- Scan des téléchargements
- Matching avec les APIs
- Auto-validation
- Validation manuelle (interactive)
- Batch transfer
- Résumé final

Responsabilités:
- Orchestration des étapes du workflow
- Gestion de l'état du workflow (résultats intermédiaires)
- Délégation aux services existants pour la logique métier
- Gestion du mode dry-run
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.core.entities.media import Episode, Movie, Series
from src.core.entities.video import PendingValidation, ValidationStatus
from src.core.value_objects.parsed_info import MediaType

if TYPE_CHECKING:
    from src.adapters.api.tmdb_client import TMDBClient
    from src.adapters.api.tvdb_client import TVDBClient
    from src.adapters.cli.validation import ConflictResolution
    from src.container import Container
    from src.services.matcher import MatcherService
    from src.services.organizer import OrganizerService
    from src.services.renamer import RenamerService
    from src.services.scanner import ScannerService
    from src.services.transferer import TransfererService
    from src.services.validation import ValidationService


class WorkflowStep(str, Enum):
    """Étapes du workflow."""

    CLEANUP_ORPHANS = "cleanup_orphans"
    SCAN_DOWNLOADS = "scan_downloads"
    MATCHING = "matching"
    AUTO_VALIDATION = "auto_validation"
    MANUAL_VALIDATION = "manual_validation"
    BATCH_TRANSFER = "batch_transfer"
    SUMMARY = "summary"


@dataclass
class WorkflowConfig:
    """Configuration du workflow."""

    filter_type: str = "all"  # all, movies, series
    dry_run: bool = False
    storage_dir: Path = field(default_factory=lambda: Path("."))
    video_dir: Path = field(default_factory=lambda: Path("."))

    # Répertoires de staging pour les conflits
    video_staging_dir: Optional[Path] = None
    storage_staging_dir: Optional[Path] = None

    def __post_init__(self):
        if self.video_staging_dir is None:
            self.video_staging_dir = self.video_dir.parent / "staging"
        if self.storage_staging_dir is None:
            self.storage_staging_dir = self.storage_dir / "staging"


@dataclass
class WorkflowState:
    """État du workflow pendant son exécution."""

    # Résultats intermédiaires
    scan_results: list = field(default_factory=list)
    undersized_results: list = field(default_factory=list)
    pending_validations: list[PendingValidation] = field(default_factory=list)

    # IDs créés pour nettoyage dry-run
    created_video_file_ids: list[str] = field(default_factory=list)

    # Compteurs
    orphan_count: int = 0
    auto_validated_count: int = 0
    manual_validated_count: int = 0

    # Transferts construits
    transfers: list[dict] = field(default_factory=list)

    # Résolution de conflits (cache)
    conflict_decisions: dict[str, "ConflictResolution"] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """Résultat final du workflow."""

    success: bool
    state: WorkflowState
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        """Nombre total de fichiers traités."""
        return len(self.state.scan_results)

    @property
    def total_validated(self) -> int:
        """Nombre total de fichiers validés."""
        return self.state.auto_validated_count + self.state.manual_validated_count


class WorkflowService:
    """
    Service d'orchestration du workflow complet.

    Ce service coordonne les différentes étapes du traitement des vidéos,
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
            container: Container d'injection de dépendances
            console: Console Rich pour les affichages (créée si None)
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

        # Services (récupérés depuis le container ou injectés)
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
        Exécute le workflow complet avec la configuration donnée.

        Args:
            config: Configuration du workflow

        Returns:
            WorkflowResult avec l'état final et les erreurs éventuelles
        """
        # Initialiser les services
        self._initialize_services(config)

        # Initialiser l'état
        state = WorkflowState()

        try:
            # Étape 1: Nettoyage des orphelins
            await self._cleanup_orphans(state)

            # Étape 2: Scan des téléchargements
            await self._scan_downloads(config, state)

            if not state.scan_results:
                self._console.print("[yellow]Aucun fichier à traiter.[/yellow]")
                return WorkflowResult(success=True, state=state)

            # Étape 3: Matching avec les APIs
            await self._perform_matching(state)

            # Étape 4: Auto-validation
            await self._auto_validate(state)

            # Étape 5: Validation manuelle (si pas dry-run)
            if not config.dry_run:
                await self._manual_validate(state)

            # Étape 6: Batch transfer ou affichage dry-run
            await self._batch_transfer(config, state)

            # Étape 7: Résumé final
            self._print_summary(state)

            # Étape 8: Nettoyage dry-run
            if config.dry_run:
                await self._cleanup_dry_run(state)

            return WorkflowResult(success=True, state=state)

        except Exception as e:
            logger.exception(f"Erreur lors du workflow: {e}")
            return WorkflowResult(success=False, state=state, errors=[str(e)])

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _initialize_services(self, config: WorkflowConfig) -> None:
        """Initialise les services nécessaires depuis le container ou utilise ceux injectés."""
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

    # ------------------------------------------------------------------
    # Étape 1: Nettoyage des orphelins
    # ------------------------------------------------------------------

    async def _cleanup_orphans(self, state: WorkflowState) -> None:
        """
        Nettoie les enregistrements orphelins des exécutions précédentes.

        Supprime les PendingValidation et VideoFile qui n'ont pas été
        transférés (runs précédents interrompus).
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

    # ------------------------------------------------------------------
    # Étape 2: Scan des téléchargements
    # ------------------------------------------------------------------

    async def _scan_downloads(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """
        Scan le répertoire des téléchargements.

        Détecte les fichiers vidéo et gère les fichiers sous le seuil de taille.
        """
        self._console.print("\n[bold cyan]Étape 1/4: Scan des téléchargements[/bold cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        ) as progress:
            scan_task = progress.add_task("[cyan]Scan en cours...", total=None)

            for result in self._scanner.scan_downloads():
                # Filtrer selon filter_type
                if self._should_filter(result, config.filter_type):
                    continue

                state.scan_results.append(result)
                progress.update(
                    scan_task, description=f"[cyan]{result.video_file.filename}"
                )

            progress.update(
                scan_task, total=len(state.scan_results), completed=len(state.scan_results)
            )

        self._console.print(f"[bold]{len(state.scan_results)}[/bold] fichier(s) trouvé(s)")

        # Gestion des fichiers sous le seuil
        await self._handle_undersized_files(config, state)

    def _should_filter(self, scan_result, filter_type: str) -> bool:
        """Détermine si un résultat doit être filtré selon le type."""
        if filter_type == "all":
            return False
        if filter_type == "movies":
            return scan_result.detected_type != MediaType.MOVIE
        if filter_type == "series":
            return scan_result.detected_type != MediaType.SERIES
        return False

    async def _handle_undersized_files(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """
        Gère les fichiers sous le seuil de taille.

        Regroupe par titre/série et demande confirmation à l'utilisateur.
        """
        from collections import defaultdict
        from rich.prompt import Confirm

        undersized_results = list(self._scanner.scan_undersized_files())

        # Filtrer selon filter_type
        undersized_results = [
            r for r in undersized_results
            if not self._should_filter(r, config.filter_type)
        ]

        if not undersized_results:
            return

        # Grouper par titre
        undersized_groups: dict[str, list] = defaultdict(list)

        for result in undersized_results:
            title = result.parsed_info.title or "Inconnu"
            undersized_groups[title].append(result)

        config_obj = self._container.config()
        self._console.print(
            f"\n[yellow]⚠ {len(undersized_results)} fichier(s) sous le seuil de "
            f"{config_obj.min_file_size_mb} Mo détecté(s)[/yellow]"
        )

        for title, group in undersized_groups.items():
            total_size_mb = sum(r.video_file.size_bytes for r in group) / (1024 * 1024)
            file_count = len(group)
            is_series = group[0].detected_type == MediaType.SERIES

            if is_series:
                self._console.print(
                    f"\n[bold]{title}[/bold] - {file_count} episode(s), {total_size_mb:.1f} Mo total"
                )
            else:
                self._console.print(f"\n[bold]{title}[/bold] - {total_size_mb:.1f} Mo")

            # Afficher quelques exemples
            for r in group[:3]:
                size_mb = r.video_file.size_bytes / (1024 * 1024)
                self._console.print(f"  [dim]{r.video_file.filename} ({size_mb:.1f} Mo)[/dim]")
            if len(group) > 3:
                self._console.print(f"  [dim]... et {len(group) - 3} autre(s)[/dim]")

            if Confirm.ask(
                f"Traiter {'cette série' if is_series else 'ce fichier'} ?",
                default=False
            ):
                state.scan_results.extend(group)
                self._console.print(f"  [green]✓[/green] {file_count} fichier(s) ajouté(s)")
            else:
                self._console.print(f"  [dim]Ignoré(s)[/dim]")

        if state.scan_results:
            self._console.print(f"\n[bold]{len(state.scan_results)}[/bold] fichier(s) total à traiter")

    # ------------------------------------------------------------------
    # Étape 3: Matching avec les APIs
    # ------------------------------------------------------------------

    async def _perform_matching(self, state: WorkflowState) -> None:
        """
        Effectue le matching avec les APIs (TMDB/TVDB).

        Crée les enregistrements VideoFile et PendingValidation.
        """
        self._console.print("\n[bold cyan]Étape 2/4: Matching avec les APIs[/bold cyan]\n")

        pending_repo = self._container.pending_validation_repository()
        video_file_repo = self._container.video_file_repository()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        ) as progress:
            match_task = progress.add_task(
                "[green]Matching...", total=len(state.scan_results)
            )

            for result in state.scan_results:
                progress.update(
                    match_task, description=f"[green]{result.video_file.filename}"
                )

                # Créer VideoFile et PendingValidation
                video_file, pending = await self._create_pending_validation(result)

                saved_vf = video_file_repo.save(video_file)
                if saved_vf.id:
                    state.created_video_file_ids.append(saved_vf.id)

                pending.video_file = saved_vf
                pending_repo.save(pending)

                progress.advance(match_task)

        self._console.print(
            f"[bold]{len(state.scan_results)}[/bold] fichier(s) en attente de validation"
        )

    async def _create_pending_validation(
        self, scan_result
    ) -> tuple["VideoFile", PendingValidation]:
        """
        Crée un VideoFile et PendingValidation à partir d'un résultat de scan.

        Effectue la recherche API et le scoring.
        """
        from src.core.entities.video import VideoFile

        # Créer VideoFile
        video_file = VideoFile(
            path=scan_result.video_file.path,
            filename=scan_result.video_file.filename,
            media_info=scan_result.media_info,
        )

        # Rechercher les candidats via API
        title = scan_result.parsed_info.title
        year = scan_result.parsed_info.year
        candidates = []

        if scan_result.detected_type == MediaType.MOVIE:
            candidates = await self._search_and_score_movie(
                title, year, scan_result.media_info
            )
        else:
            candidates = await self._search_and_score_series(title, year)

        # Convertir en dict pour stockage
        candidates_data = [
            {
                "id": c.id,
                "title": c.title,
                "year": c.year,
                "score": c.score,
                "source": c.source,
            }
            for c in candidates
        ]

        pending = PendingValidation(
            video_file=video_file,
            candidates=candidates_data,
        )

        return video_file, pending

    async def _search_and_score_movie(
        self, title: str, year: Optional[int], media_info
    ) -> list:
        """Recherche et score les films via TMDB."""
        candidates = []

        if not self._tmdb_client or not getattr(self._tmdb_client, "_api_key", None):
            return candidates

        try:
            api_results = await self._tmdb_client.search(title, year=year)
            duration = None
            if media_info and media_info.duration_seconds:
                duration = media_info.duration_seconds

            # Premier scoring sans durée API
            candidates = self._matcher.score_results(
                api_results, title, year, duration
            )

            # Enrichir les top 3 avec durée et re-scorer
            if candidates and duration:
                top_candidates = candidates[:3]
                enriched_candidates = []

                for cand in top_candidates:
                    try:
                        details = await self._tmdb_client.get_details(cand.id)
                        if details and details.duration_seconds:
                            from src.services.matcher import calculate_movie_score
                            from dataclasses import replace

                            new_score = calculate_movie_score(
                                query_title=title,
                                query_year=year,
                                query_duration=duration,
                                candidate_title=cand.title,
                                candidate_year=cand.year,
                                candidate_duration=details.duration_seconds,
                                candidate_original_title=(
                                    cand.original_title or details.original_title
                                ),
                            )
                            cand = replace(cand, score=new_score)
                    except Exception:
                        pass
                    enriched_candidates.append(cand)

                candidates = enriched_candidates + candidates[3:]
                candidates.sort(key=lambda c: c.score, reverse=True)

        except Exception as e:
            self._console.print(f"[yellow]Erreur TMDB pour {title}: {e}[/yellow]")

        return candidates

    async def _search_and_score_series(
        self, title: str, year: Optional[int]
    ) -> list:
        """Recherche et score les séries via TVDB."""
        candidates = []

        if not self._tvdb_client or not getattr(self._tvdb_client, "_api_key", None):
            return candidates

        try:
            api_results = await self._tvdb_client.search(title, year=year)
            candidates = self._matcher.score_results(
                api_results, title, year, None, is_series=True
            )
        except Exception as e:
            self._console.print(f"[yellow]Erreur TVDB pour {title}: {e}[/yellow]")

        return candidates

    # ------------------------------------------------------------------
    # Étape 4: Auto-validation
    # ------------------------------------------------------------------

    async def _auto_validate(self, state: WorkflowState) -> None:
        """
        Effectue l'auto-validation des fichiers.

        Utilise le ValidationService pour valider automatiquement
        les fichiers avec score >= 85% et candidat unique.
        """
        self._console.print("\n[bold cyan]Étape 3/4: Auto-validation[/bold cyan]\n")

        pending_list = self._validation_service.list_pending()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        ) as progress:
            auto_task = progress.add_task(
                "[magenta]Auto-validation...", total=len(pending_list)
            )

            for pend in pending_list:
                result = await self._validation_service.process_auto_validation(pend)
                if result.auto_validated:
                    state.auto_validated_count += 1
                progress.advance(auto_task)

        self._console.print(f"[bold]{state.auto_validated_count}[/bold] fichier(s) auto-validé(s)")

    # ------------------------------------------------------------------
    # Étape 5: Validation manuelle
    # ------------------------------------------------------------------

    async def _manual_validate(self, state: WorkflowState) -> None:
        """
        Effectue la validation manuelle interactive.

        Utilise validation_loop depuis src.adapters.cli.validation.
        """
        from src.adapters.cli.validation import validation_loop
        from src.adapters.cli.commands import _get_series_folder

        remaining = [
            p for p in self._validation_service.list_pending()
            if p.validation_status == ValidationStatus.PENDING and not p.auto_validated
        ]

        if not remaining:
            return

        self._console.print(
            f"\n[bold cyan]Étape 4/4: Validation manuelle[/bold cyan] "
            f"({len(remaining)} fichier(s))\n"
        )

        processed_ids: set[str] = set()

        for pend in remaining:
            if pend.id and pend.id in processed_ids:
                continue

            result = await validation_loop(pend, self._validation_service)

            if result == "quit":
                self._console.print("[yellow]Validation interrompue.[/yellow]")
                break
            elif result == "trash":
                self._validation_service.reject_pending(pend)
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[red]Corbeille:[/red] {filename}")
            elif result is None:
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[yellow]Passé:[/yellow] {filename}")
            else:
                candidate = result
                await self._validation_service.validate_candidate(pend, candidate)
                state.manual_validated_count += 1
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[green]Validé:[/green] {filename}")

                # Auto-validation des autres épisodes de la même série
                if candidate.source == "tvdb":
                    await self._auto_validate_series_episodes(
                        pend, candidate, remaining, processed_ids, state
                    )

        self._console.print(
            f"\n[bold]{state.manual_validated_count}[/bold] fichier(s) validé(s) manuellement"
        )

    async def _auto_validate_series_episodes(
        self, pend, candidate, remaining: list, processed_ids: set, state: WorkflowState
    ) -> None:
        """Auto-valide les autres épisodes de la même série."""
        from src.adapters.cli.commands import _get_series_folder

        current_folder = _get_series_folder(pend)
        if not current_folder:
            return

        auto_validated_episodes = 0

        for other in remaining:
            if other.id == pend.id or (other.id and other.id in processed_ids):
                continue

            other_folder = _get_series_folder(other)
            if other_folder == current_folder:
                await self._validation_service.validate_candidate(other, candidate)
                processed_ids.add(other.id)
                state.manual_validated_count += 1
                auto_validated_episodes += 1
                other_filename = other.video_file.filename if other.video_file else "?"
                self._console.print(f"[green]  ↳ Auto-validé:[/green] {other_filename}")

        if auto_validated_episodes > 0:
            self._console.print(
                f"[cyan]{auto_validated_episodes} autre(s) episode(s) "
                f"auto-validé(s) pour cette série[/cyan]"
            )

    # ------------------------------------------------------------------
    # Étape 6: Batch transfer
    # ------------------------------------------------------------------

    async def _batch_transfer(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """
        Construit et exécute le batch de transferts.

        En mode dry-run: affiche l'arborescence
        En mode normal: exécute les transferts après confirmation
        """
        from src.adapters.cli.batch_builder import build_transfers_batch
        from src.adapters.cli.commands import _display_transfer_tree
        from src.adapters.cli.validation import display_batch_summary, execute_batch_transfer
        from rich.prompt import Confirm

        validated_list = self._validation_service.list_validated()

        # Filtrer pour ne traiter que les fichiers de cette session
        session_validated = [
            v for v in validated_list
            if v.video_file and v.video_file.id in state.created_video_file_ids
        ]

        if not session_validated:
            return

        # Construire les transferts
        transfers = await build_transfers_batch(
            session_validated,
            self._container,
            config.storage_dir,
            config.video_dir,
        )
        state.transfers = transfers

        if config.dry_run:
            await self._display_dry_run(config, state)
        else:
            await self._execute_transfers(config, state)

    async def _display_dry_run(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """Affiche le résultat en mode dry-run."""
        from src.adapters.cli.commands import _display_transfer_tree

        self._console.print(
            "\n[yellow]Mode dry-run - aucun transfert effectué[/yellow]"
        )
        self._console.print(
            f"[dim]{len(state.transfers)} fichier(s) seraient transférés[/dim]\n"
        )

        if state.transfers:
            _display_transfer_tree(
                state.transfers, config.storage_dir, config.video_dir
            )

    async def _execute_transfers(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """Exécute les transferts après confirmation."""
        from src.adapters.cli.validation import display_batch_summary, execute_batch_transfer
        from rich.prompt import Confirm

        self._console.print(f"\n[bold cyan]Transfert des fichiers valides[/bold cyan]\n")

        display_batch_summary(state.transfers)

        if not Confirm.ask("\n[bold]Exécuter le transfert ?[/bold]", default=False):
            self._console.print("[yellow]Transfert annulé.[/yellow]")
            return

        results = await execute_batch_transfer(state.transfers, self._transferer)
        success_count = sum(1 for r in results if r.get("success", False))

        self._console.print(
            f"\n[bold green]{success_count}[/bold green] fichier(s) transféré(s)"
        )

    # ------------------------------------------------------------------
    # Étape 7: Résumé
    # ------------------------------------------------------------------

    def _print_summary(self, state: WorkflowState) -> None:
        """Affiche le résumé final du workflow."""
        self._console.print("\n[bold]Résumé:[/bold]")
        self._console.print(f"  Scannés: {len(state.scan_results)}")
        self._console.print(f"  Auto-validés: {state.auto_validated_count}")

        if state.manual_validated_count > 0:
            self._console.print(f"  Validés manuellement: {state.manual_validated_count}")

        validated_total = state.auto_validated_count + state.manual_validated_count
        if validated_total > 0:
            self._console.print(f"  Total validés: {validated_total}")

    # ------------------------------------------------------------------
    # Étape 8: Nettoyage dry-run
    # ------------------------------------------------------------------

    async def _cleanup_dry_run(self, state: WorkflowState) -> None:
        """
        Nettoie les données temporaires créées pendant le dry-run.

        Supprime les PendingValidation et VideoFile créés pendant
        l'exécution du workflow en mode dry-run.
        """
        if not state.created_video_file_ids:
            return

        pending_repo = self._container.pending_validation_repository()
        video_file_repo = self._container.video_file_repository()

        # Supprimer d'abord les PendingValidation
        for vf_id in state.created_video_file_ids:
            pv = pending_repo.get_by_video_file_id(vf_id)
            if pv and pv.id:
                pending_repo.delete(pv.id)

        # Puis supprimer les VideoFile
        for vf_id in state.created_video_file_ids:
            video_file_repo.delete(vf_id)

        self._console.print(
            f"\n[dim]Dry-run: {len(state.created_video_file_ids)} enregistrement(s) "
            f"temporaire(s) nettoyé(s)[/dim]"
        )
