"""
Helpers CLI pour la commande consolidate.

Ce module fournit les fonctions utilitaires pour l'affichage des rapports
de consolidation de symlinks externes.

Responsabilites:
- Affichage du résumé de consolidation par volume
- Affichage des exemples de symlinks externes
- Affichage du résumé final de consolidation
"""

from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from src.services.consolidation import ConsolidationStatus, ExternalSymlink


def display_summary(symlinks: list["ExternalSymlink"], summary: dict) -> None:
    """
    Affiche le résumé de consolidation par volume sous forme de tableau.

    Args:
        symlinks: Liste des symlinks externes trouves
        summary: Dictionnaire des statistiques par volume
    """
    from src.adapters.cli.helpers import console

    console.print(f"\n[bold]Symlinks externes:[/bold] {len(symlinks)}\n")

    table = Table(title="Resume par volume")
    table.add_column("Volume", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Accessibles", justify="right", style="green")
    table.add_column("Inaccessibles", justify="right", style="red")
    table.add_column("Taille", justify="right")

    for volume, stats in summary.items():
        size_gb = stats["total_size"] / (1024**3) if stats["total_size"] else 0
        table.add_row(
            volume,
            str(stats["count"]),
            str(stats["accessible"]),
            str(stats["inaccessible"]),
            f"{size_gb:.1f} Go",
        )

    console.print(table)


def display_inaccessible_warning(inaccessible_count: int) -> None:
    """
    Affiche un avertissement pour les fichiers inaccessibles.

    Args:
        inaccessible_count: Nombre de fichiers inaccessibles
    """
    from src.adapters.cli.helpers import console

    if inaccessible_count > 0:
        console.print(f"\n[yellow]Attention:[/yellow] {inaccessible_count} fichiers inaccessibles")
        console.print("[dim]Volumes non montes ou permissions insuffisantes[/dim]")


def display_examples(symlinks: list["ExternalSymlink"]) -> None:
    """
    Affiche des exemples de symlinks externes.

    Args:
        symlinks: Liste des symlinks externes
    """
    from src.adapters.cli.helpers import console
    from src.services.consolidation import ConsolidationStatus

    console.print("\n[dim]Exemples de symlinks externes:[/dim]")
    for s in symlinks[:5]:
        status_icon = "[green]✓[/green]" if s.status == ConsolidationStatus.ACCESSIBLE else "[red]✗[/red]"
        console.print(f"  {status_icon} {s.symlink_path.name}")
        console.print(f"    [dim]-> {s.target_path}[/dim]")

    if len(symlinks) > 5:
        console.print(f"  [dim]... et {len(symlinks) - 5} autres[/dim]")


def display_consolidation_prompt() -> None:
    """Affiche le message d'instruction pour la consolidation."""
    from src.adapters.cli.helpers import console

    console.print(f"\n[cyan]Pour rapatrier les fichiers accessibles:[/cyan]")
    console.print(f"  cineorg consolidate --consolidate")


def display_final_summary(
    consolidated: int,
    errors: int,
    inaccessible_count: int,
    dry_run: bool = False,
) -> None:
    """
    Affiche le résumé final de la consolidation.

    Args:
        consolidated: Nombre de fichiers consolidés
        errors: Nombre d'erreurs
        inaccessible_count: Nombre de fichiers inaccessibles
        dry_run: Mode simulation
    """
    from src.adapters.cli.helpers import console

    console.print(f"\n[bold]Resume:[/bold]")
    console.print(f"  [green]{consolidated}[/green] fichier(s) rapatrie(s)")
    if errors:
        console.print(f"  [red]{errors}[/red] erreur(s)")
    console.print(f"  [yellow]{inaccessible_count}[/yellow] inaccessible(s)")


class ConsolidationProgress:
    """
    Gestion de l'affichage de la progression de consolidation.

    Responsabilites:
    - Affichage de la barre de progression
    - Mise a jour des statistiques en temps réel
    """

    @staticmethod
    def display_initial_message(count: int, dry_run: bool) -> None:
        """
        Affiche le message initial de consolidation.

        Args:
            count: Nombre de fichiers a consolider
            dry_run: Mode simulation
        """
        from src.adapters.cli.helpers import console

        mode_label = "[dim](dry-run)[/dim] " if dry_run else ""
        console.print(f"\n[bold cyan]{mode_label}Rapatriement de {count} fichiers...[/bold cyan]\n")

    @staticmethod
    def display_error(symlink_name: str, error_message: str) -> None:
        """
        Affiche une erreur de consolidation.

        Args:
            symlink_name: Nom du symlink
            error_message: Message d'erreur
        """
        from src.adapters.cli.helpers import console

        console.print(f"[red]Erreur:[/red] {symlink_name}: {error_message}")
