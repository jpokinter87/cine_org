"""
Mode automatique de reparation des symlinks casses.

Repare automatiquement les symlinks avec un score >= 90%.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.services.integrity import RepairAction, RepairActionType

if TYPE_CHECKING:
    from src.services.integrity import RepairService

    from .title_resolver import TitleResolver


class AutoRepair:
    """
    Gestion du mode automatique de réparation.

    Responsabilites:
    - Boucle de réparation automatique avec Progress
    - Réparation des symlinks avec score >= 90%
    - Comptage des statistiques (reparés, ignorés, sans candidat)
    """

    @staticmethod
    async def run(
        repair: "RepairService",
        broken: list[Path],
        min_score: float,
        dry_run: bool,
        title_resolver: "TitleResolver | None" = None,
    ) -> tuple[list[RepairAction], int, int]:
        """
        Exécute le mode automatique de réparation.

        Args:
            repair: RepairService
            broken: Liste des symlinks casses
            min_score: Score minimum pour réparation
            dry_run: Mode simulation
            title_resolver: Resolveur de titres TMDB optionnel

        Returns:
            Tuple (actions, auto_repaired, no_match_count)
        """
        from src.adapters.cli.helpers import console

        actions: list[RepairAction] = []
        auto_repaired = 0
        no_match_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Recherche et reparation...", total=len(broken))

            for link in broken:
                short_name = link.name[:60]
                progress.update(task, description=f"[cyan]{short_name}]")

                # Obtenir les titres alternatifs via TMDB
                alt_names = []
                if title_resolver:
                    alt_names = await title_resolver.get_alternative_names(link)

                # Chercher des cibles possibles avec recherche floue
                targets_with_scores = repair.find_possible_targets(
                    link, min_score=min_score, alternative_names=alt_names or None
                )

                # Reparer si score >= 90%
                if targets_with_scores and targets_with_scores[0][1] >= 90:
                    best_target, best_score = targets_with_scores[0]
                    if not dry_run:
                        success = repair.repair_symlink(link, best_target)
                    else:
                        success = True

                    if success:
                        actions.append(
                            RepairAction(
                                link=link,
                                action=RepairActionType.REPAIRED,
                                new_target=best_target,
                            )
                        )
                        auto_repaired += 1
                        # Afficher en vert au-dessus de la barre
                        progress.console.print(f"[green]✓[/green] {short_name}")
                else:
                    if not targets_with_scores:
                        no_match_count += 1
                        # Afficher en rouge au-dessus de la barre
                        progress.console.print(f"[red]✗[/red] {short_name}")
                    else:
                        # Afficher en jaune au-dessus de la barre
                        progress.console.print(f"[yellow]~[/yellow] {short_name}")
                    actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))

                progress.advance(task)

            progress.update(task, description="[green]Termine")

        return actions, auto_repaired, no_match_count

    @staticmethod
    def display_summary(auto_repaired: int, broken_count: int, no_match_count: int) -> None:
        """
        Affiche le résumé des réparations automatiques.

        Args:
            auto_repaired: Nombre de symlinks réparés
            broken_count: Nombre total de symlinks casses
            no_match_count: Nombre sans candidat
        """
        from src.adapters.cli.helpers import console

        console.print(f"\n[bold]Reparations automatiques:[/bold]")
        console.print(f"  [green]{auto_repaired}[/green] repare(s) (score >= 90%)")
        console.print(f"  [yellow]{broken_count - auto_repaired - no_match_count}[/yellow] ignore(s) (score < 90%)")
        console.print(f"  [red]{no_match_count}[/red] sans candidat")
