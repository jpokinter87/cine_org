"""
Etape de transfert du workflow : construction du batch, dry-run et execution.
"""

from .dataclasses import WorkflowConfig, WorkflowState


class TransferStepMixin:
    """Mixin pour l'etape de transfert et resume."""

    async def _batch_transfer(self, config: WorkflowConfig, state: WorkflowState) -> None:
        """
        Construit et exécute le batch de transferts.

        En mode dry-run: affiche l'arborescence
        En mode normal: exécute les transferts après confirmation
        """
        from src.adapters.cli.batch_builder import build_transfers_batch
        from src.adapters.cli.helpers import _display_transfer_tree
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
        from src.adapters.cli.helpers import _display_transfer_tree

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
