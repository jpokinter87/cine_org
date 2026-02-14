"""
Etape de scan du workflow : scan des telechargements et gestion des fichiers sous-dimensionnes.
"""

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.core.value_objects.parsed_info import MediaType

from .dataclasses import WorkflowConfig, WorkflowState


class ScanStepMixin:
    """Mixin pour l'etape de scan des telechargements."""

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
