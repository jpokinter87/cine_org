"""Commande CLI cleanup : nettoyage et reorganisation du repertoire video."""

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.adapters.cli.validation import console
from src.container import Container
from src.services.cleanup import load_report_cache, save_report_cache


def cleanup(
    video_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire video a nettoyer (defaut: video_dir de la config)",
        ),
    ] = None,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Executer les corrections (defaut: rapport seul)"),
    ] = False,
    skip_repair: Annotated[
        bool,
        typer.Option("--skip-repair", help="Ne pas reparer les symlinks casses"),
    ] = False,
    skip_subdivide: Annotated[
        bool,
        typer.Option("--skip-subdivide", help="Ne pas subdiviser les repertoires"),
    ] = False,
    min_score: Annotated[
        float,
        typer.Option("--min-score", help="Score minimum pour auto-reparation (0-100)"),
    ] = 90.0,
    max_per_dir: Annotated[
        int,
        typer.Option("--max-per-dir", help="Nombre max de sous-repertoires avant subdivision"),
    ] = 50,
) -> None:
    """Nettoie et reorganise le repertoire video."""
    asyncio.run(_cleanup_async(video_dir, fix, skip_repair, skip_subdivide, min_score, max_per_dir))


async def _cleanup_async(
    video_dir_arg: Optional[Path],
    fix: bool,
    skip_repair: bool,
    skip_subdivide: bool,
    min_score: float,
    max_per_dir: int,
) -> None:
    """Implementation async de la commande cleanup."""
    from loguru import logger as loguru_logger
    from rich.status import Status

    from src.adapters.cli.cleanup_helpers import display_cleanup_report
    from src.services.cleanup import CleanupReport, CleanupResult

    container = Container()
    config = container.config()
    container.database.init()

    # Resoudre video_dir
    video_dir = video_dir_arg if video_dir_arg else Path(config.video_dir)

    if not video_dir.exists():
        console.print(f"[red]Erreur: Repertoire introuvable: {video_dir}[/red]")
        raise typer.Exit(1)

    # Creer le service de reparation pour le cleanup
    repair = container.repair_service(
        storage_dir=Path(config.storage_dir),
        video_dir=video_dir,
        trash_dir=Path(config.storage_dir) / ".trash",
    )

    # Creer le service de cleanup
    cleanup_svc = container.cleanup_service(
        repair_service=repair,
    )

    loguru_logger.disable("src")

    try:
        # Construire l'index fichiers
        with Status("[cyan]Indexation du stockage...", console=console) as status:
            def update_status(count: int, msg: str) -> None:
                status.update(f"[cyan]Indexation: {count} fichiers...")

            file_count = repair.build_file_index(progress_callback=update_status)

        console.print(f"[bold cyan]Index:[/bold cyan] {file_count} fichiers indexes\n")

        # En mode --fix, tenter de charger le cache
        report = None
        if fix:
            cached = load_report_cache(video_dir)
            if cached is not None:
                console.print(
                    "[bold cyan]Utilisation de l'analyse en cache[/bold cyan]\n"
                )
                report = cached

        # Analyse si pas de cache
        if report is None:
            with Status("[cyan]Analyse du repertoire video...", console=console):
                report = cleanup_svc.analyze(video_dir, max_per_dir=max_per_dir)

        # Afficher le rapport
        display_cleanup_report(report, video_dir)

        if not fix:
            # Sauvegarder le cache pour un futur --fix
            save_report_cache(report)

        if not report.has_issues:
            console.print("[green]Aucun probleme detecte.[/green]")
            return

        if not fix:
            console.print(
                "\n[dim]Pour corriger : cineorg cleanup --fix[/dim]"
            )
            return

        # Executer les corrections
        console.print("\n[bold cyan]Execution des corrections[/bold cyan]\n")

        # 1. Reparer symlinks casses (score >= min_score)
        if not skip_repair and report.broken_symlinks:
            repairable = [
                b for b in report.broken_symlinks
                if b.best_candidate and b.candidate_score >= min_score
            ]
            unrepairable = [
                b for b in report.broken_symlinks
                if b.best_candidate is None or b.candidate_score < min_score
            ]

            if repairable:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        "[cyan]Reparation des symlinks...",
                        total=len(repairable),
                    )
                    result = cleanup_svc.repair_broken_symlinks(
                        repairable, min_score=min_score,
                    )
                    progress.update(task, completed=len(repairable))

                console.print(
                    f"  Symlinks repares: [green]{result.repaired_symlinks}[/green]"
                    f"  Echecs: [red]{result.failed_repairs}[/red]"
                )

            # 1b. Supprimer les symlinks casses irreparables
            if unrepairable:
                result = cleanup_svc.delete_broken_symlinks(unrepairable)
                console.print(
                    f"  Symlinks irreparables supprimes: [yellow]{result.broken_symlinks_deleted}[/yellow]"
                )

        # 2. Corriger symlinks mal places
        if report.misplaced_symlinks:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "[cyan]Deplacement des symlinks...",
                    total=len(report.misplaced_symlinks),
                )
                result = cleanup_svc.fix_misplaced_symlinks(report.misplaced_symlinks)
                progress.update(task, completed=len(report.misplaced_symlinks))

            console.print(
                f"  Symlinks deplaces: [green]{result.moved_symlinks}[/green]"
            )

        # 3. Supprimer symlinks dupliques
        if report.duplicate_symlinks:
            total_remove = sum(len(d.remove) for d in report.duplicate_symlinks)
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "[cyan]Suppression des symlinks dupliques...",
                    total=total_remove,
                )
                result = cleanup_svc.fix_duplicate_symlinks(report.duplicate_symlinks)
                progress.update(task, completed=total_remove)

            console.print(
                f"  Symlinks dupliques supprimes: [green]{result.duplicate_symlinks_removed}[/green]"
            )

        # 4. Subdiviser repertoires surcharges
        if not skip_subdivide and report.oversized_dirs:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "[cyan]Subdivision des repertoires...",
                    total=len(report.oversized_dirs),
                )
                result = cleanup_svc.subdivide_oversized_dirs(report.oversized_dirs)
                progress.update(task, completed=len(report.oversized_dirs))

            console.print(
                f"  Subdivisions: [green]{result.subdivisions_created}[/green]"
                f"  Symlinks redistribues: [green]{result.symlinks_redistributed}[/green]"
            )

        # 5. Nettoyer repertoires vides
        if report.empty_dirs:
            result = cleanup_svc.clean_empty_dirs(report.empty_dirs)
            console.print(
                f"  Repertoires vides supprimes: [green]{result.empty_dirs_removed}[/green]"
            )

        console.print("\n[bold green]Nettoyage termine.[/bold green]")

    finally:
        loguru_logger.enable("src")
