"""Commande CLI regroup : detection des prefixes recurrents et regroupement de fichiers."""

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
from rich.tree import Tree

from src.adapters.cli.validation import console
from src.container import Container


def regroup(
    video_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire video a analyser (defaut: video_dir de la config)",
        ),
    ] = None,
    min_count: Annotated[
        int,
        typer.Option("--min-count", help="Nombre minimum de fichiers pour creer un groupe"),
    ] = 3,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Executer les deplacements (defaut: analyse seule)"),
    ] = False,
    storage_dir: Annotated[
        Optional[Path],
        typer.Option("--storage-dir", help="Repertoire storage correspondant"),
    ] = None,
) -> None:
    """Detecte les prefixes recurrents et regroupe les fichiers."""
    asyncio.run(_regroup_async(video_dir, min_count, fix, storage_dir))


async def _regroup_async(
    video_dir_arg: Optional[Path],
    min_count: int,
    fix: bool,
    storage_dir_arg: Optional[Path],
) -> None:
    """Implementation async de la commande regroup."""
    from loguru import logger as loguru_logger

    from src.services.prefix_grouper import (
        PrefixGrouperService,
        load_regroup_cache,
        save_regroup_cache,
    )

    container = Container()
    config = container.config()

    # Resoudre les repertoires
    storage_dir = storage_dir_arg if storage_dir_arg else Path(config.storage_dir)

    loguru_logger.disable("src")

    try:
        service = PrefixGrouperService()
        groups = None

        # En mode --fix sans video_dir explicite, tenter de charger le cache
        if fix and video_dir_arg is None:
            cached = load_regroup_cache()
            if cached is not None:
                video_dir, cached_storage, groups = cached
                if storage_dir_arg is None:
                    storage_dir = cached_storage
                console.print(
                    f"[bold cyan]Utilisation de l'analyse en cache pour {video_dir}[/bold cyan]\n"
                )

        # Resoudre video_dir si pas encore defini par le cache
        if groups is None:
            video_dir = video_dir_arg if video_dir_arg else Path(config.video_dir)

        if not video_dir.exists():
            console.print(f"[red]Erreur: Repertoire introuvable: {video_dir}[/red]")
            raise typer.Exit(1)

        # Analyse si pas de cache charge
        if groups is None:
            console.print(f"[bold cyan]Analyse des prefixes dans {video_dir}[/bold cyan]\n")
            groups = service.analyze(video_dir, min_count=min_count)

        if not groups:
            console.print("[green]Aucun regroupement detecte.[/green]")
            return

        # Affichage des groupes detectes avec arborescence projetee
        total_files = 0

        # Regrouper les groupes par parent_dir pour un affichage clair
        from collections import defaultdict
        groups_by_parent: dict[Path, list] = defaultdict(list)
        for group in groups:
            groups_by_parent[group.parent_dir].append(group)

        for parent_dir, dir_groups in groups_by_parent.items():
            try:
                rel_parent = parent_dir.relative_to(video_dir)
            except ValueError:
                rel_parent = parent_dir

            console.print(f"\n[bold]Modifications projetees dans {rel_parent}/[/bold] :")

            parent_tree = Tree(f"[dim]{rel_parent}/[/dim]")

            for group in dir_groups:
                # Sous-repertoire prefixe a creer
                prefix_node = parent_tree.add(
                    f"[cyan bold]{group.prefix}/[/cyan bold] [dim](nouveau)[/dim]"
                )

                sorted_files = sorted(group.files, key=lambda p: p.name)
                for f in sorted_files:
                    prefix_node.add(f"[green]{f.name}[/green] [dim]<- deplace[/dim]")

                total_files += len(group.files)

            console.print(parent_tree)

        console.print(
            f"\n[bold cyan]Total: {len(groups)} groupe(s), {total_files} fichier(s) a deplacer[/bold cyan]"
        )

        if not fix:
            # Sauvegarder le cache pour un futur --fix
            save_regroup_cache(video_dir, storage_dir, groups)

            console.print(
                "\n[dim]Pour executer : cineorg regroup --fix[/dim]"
            )
            return

        # Execution
        console.print("\n[bold cyan]Execution des regroupements[/bold cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "[cyan]Regroupement des fichiers...",
                total=total_files,
            )
            completed = 0

            def on_group_done(prefix: str, count: int) -> None:
                nonlocal completed
                completed += count
                progress.update(task, completed=completed, description=f"[cyan]{prefix}/")

            moved = service.execute(groups, video_dir, storage_dir, progress_callback=on_group_done)

        console.print(
            f"\n[bold green]Regroupement termine: {moved} fichier(s) deplace(s).[/bold green]"
        )

    finally:
        loguru_logger.enable("src")
