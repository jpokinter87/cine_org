"""
Commandes CLI pour le workflow principal (process, pending).
"""

import asyncio
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console


class MediaFilter(str, Enum):
    """Filtre par type de media."""

    ALL = "all"
    MOVIES = "movies"
    SERIES = "series"


def process(
    filter_type: Annotated[
        MediaFilter,
        typer.Option("--filter", "-f", help="Type de medias a traiter"),
    ] = MediaFilter.ALL,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier les fichiers"),
    ] = False,
) -> None:
    """Execute le workflow complet: scan -> matching -> validation -> transfert."""
    asyncio.run(_process_async(filter_type, dry_run))


@with_container()
async def _process_async(container, filter_type: MediaFilter, dry_run: bool) -> None:
    """Implementation async du workflow complet."""
    from src.services.workflow import WorkflowService, WorkflowConfig

    config_obj = container.config()

    workflow_config = WorkflowConfig(
        filter_type=filter_type.value,
        dry_run=dry_run,
        storage_dir=Path(config_obj.storage_dir),
        video_dir=Path(config_obj.video_dir),
    )

    workflow = WorkflowService(container, console=console)
    result = await workflow.execute(workflow_config)

    if not result.success:
        console.print(f"[red]Erreur lors du workflow: {result.errors}[/red]")
        raise typer.Exit(1)


def pending(
    all_files: Annotated[
        bool,
        typer.Option("--all", "-a", help="Afficher tous les fichiers sans pagination"),
    ] = False,
) -> None:
    """Affiche les fichiers en attente de validation."""
    asyncio.run(_pending_async(all_files))


@with_container()
async def _pending_async(container, all_files: bool) -> None:
    """Implementation async de la commande pending."""

    validation_svc = container.validation_service()
    pending_list = validation_svc.list_pending()

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente.[/yellow]")
        raise typer.Exit(0)

    # Tri par score decroissant
    def get_max_score(p: "PendingValidation") -> float:
        if not p.candidates:
            return 0.0
        return max(
            (
                c.get("score", 0) if isinstance(c, dict) else c.score
                for c in p.candidates
            ),
            default=0.0,
        )

    pending_list.sort(key=get_max_score, reverse=True)

    # Affichage avec panels Rich
    page_size = len(pending_list) if all_files else 15

    for pend in pending_list[:page_size]:
        panel = _render_pending_panel(pend)
        console.print(panel)
        console.print()

    if not all_files and len(pending_list) > page_size:
        remaining = len(pending_list) - page_size
        console.print(
            f"[dim]({remaining} fichiers non affiches, utilisez --all)[/dim]"
        )

    console.print(f"\n[bold]Total: {len(pending_list)} fichier(s) en attente[/bold]")


def _render_pending_panel(pend: "PendingValidation") -> Panel:
    """Cree un panel Rich pour un fichier pending."""
    from src.core.entities.video import PendingValidation

    lines = []

    # ID du fichier pour reference
    lines.append(f"[dim]ID: {pend.id}[/dim]")

    # Nom du fichier
    filename = pend.video_file.filename if pend.video_file else "?"
    lines.append(f"[bold cyan]{filename}[/bold cyan]")

    # Meilleur candidat
    if pend.candidates:
        best = pend.candidates[0]
        title = best.get("title", "") if isinstance(best, dict) else best.title
        score = best.get("score", 0) if isinstance(best, dict) else best.score
        year = best.get("year") if isinstance(best, dict) else best.year

        score_color = "green" if score >= 85 else "yellow" if score >= 70 else "red"
        year_str = f" ({year})" if year else ""
        lines.append(f"Meilleur: {title}{year_str} [{score_color}]{score:.0f}%[/{score_color}]")
        lines.append(f"Candidats: {len(pend.candidates)}")
    else:
        lines.append("[red]Aucun candidat[/red]")

    return Panel("\n".join(lines), border_style="white")
