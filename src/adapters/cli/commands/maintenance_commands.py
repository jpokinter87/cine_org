"""
Commandes CLI de maintenance de la videotheque (repair-links, consolidate, check, cleanup, regroup).
"""

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
from src.services.cleanup import save_report_cache, load_report_cache


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
    # Utiliser un dossier trash sous storage plutot que le parent
    # pour eviter les problemes de permission (/media/trash)
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


def consolidate(
    scan_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire a scanner (defaut: storage_dir de la config)",
        ),
    ] = None,
    do_consolidate: Annotated[
        bool,
        typer.Option(
            "--consolidate",
            help="Effectue le rapatriement (sinon affiche seulement le rapport)",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Simule sans copier les fichiers",
        ),
    ] = False,
) -> None:
    """
    Detecte et rapatrie les fichiers stockes sur des volumes externes.

    Scanne la zone de stockage pour trouver les symlinks pointant vers
    d'autres volumes et permet de rapatrier les fichiers.

    Exemples:
      cineorg consolidate                    # Rapport des symlinks externes
      cineorg consolidate --consolidate      # Rapatrie les fichiers accessibles
      cineorg consolidate --consolidate --dry-run  # Simulation
    """
    from rich.status import Status

    from src.adapters.cli.consolidation_helpers import (
        ConsolidationProgress,
        display_consolidation_prompt,
        display_examples,
        display_final_summary,
        display_inaccessible_warning,
        display_summary,
    )
    from src.services.consolidation import (
        ConsolidationService,
        ConsolidationStatus,
        ExternalSymlink,
    )

    container = Container()
    config = container.config()

    # Determiner le repertoire a scanner
    storage_dir = scan_dir if scan_dir else Path(config.storage_dir)

    if not storage_dir.exists():
        console.print(f"[red]Erreur: Repertoire introuvable: {storage_dir}[/red]")
        raise typer.Exit(1)

    service = ConsolidationService(storage_dir, dry_run=dry_run)

    # Scanner les symlinks externes
    console.print(f"[bold cyan]Scan:[/bold cyan] {storage_dir}")

    with Status("[cyan]Recherche des symlinks externes...", console=console) as status:
        symlinks: list[ExternalSymlink] = list(service.scan_external_symlinks())
        status.update(f"[cyan]{len(symlinks)} symlinks externes trouves")

    if not symlinks:
        console.print("[green]Aucun symlink externe detecte.[/green]")
        console.print("[dim]Tous les fichiers sont dans la zone de stockage.[/dim]")
        return

    # Afficher le resume par volume
    summary = service.get_summary(symlinks)

    display_summary(symlinks, summary)

    # Compter les accessibles et inaccessibles
    accessible = [s for s in symlinks if s.status == ConsolidationStatus.ACCESSIBLE]
    inaccessible = [s for s in symlinks if s.status == ConsolidationStatus.INACCESSIBLE]

    display_inaccessible_warning(len(inaccessible))

    # Si pas de consolidation demandee, afficher quelques exemples
    if not do_consolidate:
        display_examples(symlinks)
        display_consolidation_prompt()
        return

    # Effectuer la consolidation
    if not accessible:
        console.print("\n[yellow]Aucun fichier accessible a rapatrier.[/yellow]")
        return

    ConsolidationProgress.display_initial_message(len(accessible), dry_run)

    consolidated = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Copie...", total=len(accessible))

        for symlink in accessible:
            progress.update(task, description=f"[cyan]{symlink.symlink_path.name[:40]}")

            result = service.consolidate(symlink)

            if result.status == ConsolidationStatus.CONSOLIDATED:
                consolidated += 1
            elif result.status == ConsolidationStatus.ERROR:
                errors += 1
                ConsolidationProgress.display_error(symlink.symlink_path.name, result.error_message)

            progress.advance(task)

        progress.update(task, description="[green]Termine")

    # Resume
    display_final_summary(consolidated, errors, len(inaccessible), dry_run)


def check(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Afficher le rapport au format JSON"),
    ] = False,
    verify_hash: Annotated[
        bool,
        typer.Option("--verify-hash", help="Verifier les hash de fichiers (lent)"),
    ] = False,
) -> None:
    """Verifie l'integrite de la videotheque."""
    container = Container()
    config = container.config()
    container.database.init()

    # Creer le checker avec les paths
    checker = container.integrity_checker(
        storage_dir=Path(config.storage_dir),
        video_dir=Path(config.video_dir),
    )

    console.print("[bold cyan]Verification d'integrite[/bold cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        check_task = progress.add_task("[cyan]Verification en cours...", total=None)

        report = checker.check(verify_hash=verify_hash)

        progress.update(check_task, description="[green]Termine")

    # Afficher le rapport
    if json_output:
        console.print(report.to_json())
    else:
        console.print(report.format_text())

        # Afficher les suggestions si issues detectees
        if report.has_issues and report.suggestions:
            console.print("\n[bold yellow]Commandes suggerees:[/bold yellow]")
            for suggestion in report.suggestions:
                console.print(f"  {suggestion}")


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
