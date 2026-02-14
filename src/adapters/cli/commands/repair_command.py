"""Commande CLI repair-links : detection et reparation des symlinks casses."""

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer

from src.adapters.cli.validation import console
from src.container import Container


def repair_links(
    scan_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire a scanner (defaut: video_dir de la config)",
        ),
    ] = None,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Repare automatiquement les symlinks avec score >= 90%",
        ),
    ] = False,
    min_score: Annotated[
        float,
        typer.Option(
            "--min-score",
            help="Score minimum pour proposer une cible (0-100)",
        ),
    ] = 50.0,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Simule sans modifier les symlinks",
        ),
    ] = False,
    scan_all: Annotated[
        bool,
        typer.Option(
            "--scan-all",
            help="Indexer tout le stockage (pas seulement Films/Series)",
        ),
    ] = False,
) -> None:
    """
    Detecte et repare les symlinks casses.

    Recherche floue basee sur la similarite des titres de films.

    Exemples:
      cineorg repair-links                    # Scan tout video_dir
      cineorg repair-links /path/to/Films     # Scan un repertoire specifique
      cineorg repair-links --auto             # Reparation automatique (score >= 90%)
      cineorg repair-links --auto --dry-run   # Simulation sans modification
      cineorg repair-links --scan-all         # Indexer toutes les categories NAS
    """
    asyncio.run(_repair_links_async(scan_dir, auto, min_score, dry_run, scan_all))


async def _repair_links_async(
    scan_dir: Optional[Path], auto_repair: bool, min_score: float, dry_run: bool,
    scan_all: bool = False,
) -> None:
    """Implementation async de la commande repair-links."""
    from loguru import logger as loguru_logger
    from rich.status import Status

    from src.adapters.cli.repair import (
        AutoRepair,
        InteractiveRepair,
        RepairSummary,
        TitleResolver,
    )
    from src.services.integrity import RepairAction, RepairActionType

    container = Container()
    config = container.config()
    container.database.init()

    # Creer le resolveur de titres TMDB (optionnel)
    tmdb_client = None
    try:
        tmdb_client = container.tmdb_client()
    except Exception:
        pass
    title_resolver = TitleResolver(tmdb_client) if tmdb_client else None

    # Determiner le repertoire a scanner
    video_dir = scan_dir if scan_dir else Path(config.video_dir)

    if not video_dir.exists():
        console.print(f"[red]Erreur: Repertoire introuvable: {video_dir}[/red]")
        raise typer.Exit(1)

    # Creer le service de reparation avec les paths
    repair = container.repair_service(
        storage_dir=Path(config.storage_dir),
        video_dir=video_dir,
        trash_dir=Path(config.storage_dir) / ".trash",
    )

    # Desactiver les logs loguru pendant l'affichage Rich pour eviter le melange
    loguru_logger.disable("src")

    try:
        # Trouver les symlinks casses avec indicateur de progression
        with Status(f"[cyan]Recherche des symlinks casses dans {video_dir}...", console=console) as status:
            broken = repair.find_broken_symlinks()
            status.update(f"[cyan]{len(broken)} symlinks casses trouves")

        if not broken:
            console.print("[green]Aucun symlink casse detecte.[/green]")
            return

        console.print(f"[bold cyan]Symlinks casses:[/bold cyan] {len(broken)} detecte(s) dans {video_dir}")

        # Construire l'index des fichiers pour optimiser les recherches
        storage_dir = Path(config.storage_dir)
        scope_label = "complet" if scan_all else "Films/Séries"
        with Status(f"[cyan]Indexation du stockage ({storage_dir}, {scope_label})...", console=console) as status:
            def update_status(count: int, msg: str) -> None:
                status.update(f"[cyan]Indexation du stockage: {count} fichiers...")

            file_count = repair.build_file_index(
                progress_callback=update_status,
                scan_all=scan_all,
            )

        console.print(f"[bold cyan]Index:[/bold cyan] {file_count} fichiers dans {storage_dir} ({scope_label})")

        mode_label = "[dim](dry-run)[/dim] " if dry_run else ""
        tmdb_label = " + TMDB" if title_resolver else ""
        console.print(f"\n{mode_label}[dim]Recherche: regroup cible -> index{tmdb_label}[/dim]\n")

        # Mode automatique avec AutoRepair
        if auto_repair:
            actions, auto_repaired, no_match_count = await AutoRepair.run(
                repair, broken, min_score, dry_run, title_resolver
            )
            AutoRepair.display_summary(auto_repaired, len(broken), no_match_count)

        # Mode interactif avec InteractiveRepair
        else:
            interactive = InteractiveRepair()
            actions = await interactive.run(repair, broken, min_score, dry_run, title_resolver)

        # Sauvegarder le log
        if actions:
            log_path = repair.save_log(actions)
            if log_path:
                console.print(f"\n[dim]Log sauvegarde: {log_path}[/dim]")

        # Afficher le resume
        RepairSummary.display(console, actions)

    finally:
        # Reactiver les logs loguru
        loguru_logger.enable("src")
