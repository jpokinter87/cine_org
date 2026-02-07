"""
Commandes Typer pour la validation des fichiers video.

Ce module fournit les commandes CLI:
- process: Workflow complet (scan -> matching -> validation -> transfert)
- pending: Liste des fichiers en attente de validation
- import: Import d'une videotheque existante
- validate auto: Validation automatique (score >= 85% et candidat unique)
- validate manual: Validation manuelle interactive
- validate batch: Execution du batch de transferts pour les fichiers valides
- validate file: Validation d'un fichier specifique par ID
"""

import asyncio
import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Confirm
from rich.tree import Tree

from src.core.value_objects.parsed_info import MediaType
from src.services.cleanup import save_report_cache, load_report_cache


# Pattern pour extraire saison/episode d'un nom de fichier
SERIES_INFO_PATTERN = re.compile(
    r"[Ss](\d{1,2})[Ee](\d{1,2})",  # S01E01, s1e1
    re.IGNORECASE
)


def _extract_series_info(filename: str) -> tuple[int, int]:
    """
    Extrait le numero de saison et d'episode d'un nom de fichier.

    Utilise le parser guessit pour extraire les informations de serie.
    Le titre d'episode sera recupere depuis TVDB.

    Args:
        filename: Nom du fichier video

    Returns:
        Tuple (season_number, episode_number), defaut (1, 1) si non trouve
    """
    from src.adapters.parsing.guessit_parser import GuessitFilenameParser
    from src.core.value_objects.parsed_info import MediaType

    parser = GuessitFilenameParser()
    parsed = parser.parse(filename, MediaType.SERIES)

    season = parsed.season if parsed.season else 1
    episode = parsed.episode if parsed.episode else 1

    return season, episode


def _extract_language_from_filename(filename: str) -> Optional[str]:
    """
    Extrait la langue du nom de fichier via guessit.

    Utilise comme fallback quand mediainfo ne detecte pas la langue
    des pistes audio (fichiers sans tag de langue).

    Args:
        filename: Nom du fichier video

    Returns:
        Code langue en majuscules (ex: "FR", "EN"), ou None si non trouve
    """
    from src.adapters.parsing.guessit_parser import GuessitFilenameParser

    parser = GuessitFilenameParser()
    parsed = parser.parse(filename)

    return parsed.language  # Deja en majuscules ou None


def _get_series_folder(pend) -> Optional[Path]:
    """
    Retourne le repertoire parent d'un fichier en attente de validation.

    Les episodes d'une meme serie sont generalement dans le meme repertoire.
    Utilisé pour regrouper et auto-valider les episodes apres validation du premier.

    Args:
        pend: PendingValidation avec video_file

    Returns:
        Path du repertoire parent ou None si non disponible
    """
    if pend.video_file and pend.video_file.path:
        return pend.video_file.path.parent
    return None


def _display_transfer_tree(
    transfers: list[dict], storage_dir: Path, video_dir: Path
) -> None:
    """
    Affiche l'arborescence des transferts prevus en mode dry-run.

    Organise les transferts par type (Films/Series) puis par repertoire
    pour une visualisation claire de la structure de destination (symlinks).

    Args:
        transfers: Liste des transferts avec source, destination, symlink_destination, etc.
        storage_dir: Repertoire de stockage racine (fichiers physiques)
        video_dir: Repertoire video racine (symlinks)
    """
    # Separer films et series
    movies = [t for t in transfers if not t.get("is_series", False)]
    series = [t for t in transfers if t.get("is_series", False)]

    # Arbre principal (affiche la structure des symlinks dans video_dir)
    tree = Tree(f"[bold blue]{video_dir}[/bold blue]")

    # Branche Films (structure des symlinks avec genres et subdivisions)
    if movies:
        films_branch = tree.add("[bold cyan]Films/[/bold cyan]")
        # Grouper par sous-repertoire relatif (depuis symlink_destination ou destination)
        movie_dirs: dict[str, list[dict]] = {}
        for m in movies:
            # Utiliser symlink_destination pour l'affichage (structure video avec genres)
            dest = m.get("symlink_destination") or m["destination"]
            # Chemin relatif depuis video_dir ou storage_dir
            try:
                rel_path = dest.relative_to(video_dir)
                parent = str(rel_path.parent)
            except ValueError:
                try:
                    rel_path = dest.relative_to(storage_dir)
                    parent = str(rel_path.parent)
                except ValueError:
                    parent = str(dest.parent)
            if parent not in movie_dirs:
                movie_dirs[parent] = []
            movie_dirs[parent].append(m)

        for dir_path in sorted(movie_dirs.keys()):
            dir_branch = films_branch.add(f"[cyan]{dir_path}/[/cyan]")
            for m in movie_dirs[dir_path]:
                source_name = m["source"].name if m["source"] else "?"
                new_name = m["new_filename"]
                dir_branch.add(f"[dim]{source_name}[/dim] -> [green]{new_name}[/green]")

    # Branche Series (structure avec type: Séries TV / Animation / Mangas)
    if series:
        # Grouper par type de serie, lettre, puis par serie, puis par saison
        # Structure: {type: {lettre: {serie: {saison: [episodes]}}}}
        type_groups: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}

        for s in series:
            # Utiliser symlink_destination pour extraire le type et la lettre
            symlink_dest = s.get("symlink_destination")
            series_type = "Séries TV"
            letter = "?"
            if symlink_dest:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    # Structure: Séries/{Type}/{Lettre}/{Titre}/{Saison}/fichier
                    parts = rel_path.parts
                    if len(parts) >= 5:
                        series_type = parts[1]  # Séries TV, Animation, ou Mangas
                        letter = parts[2]  # Lettre ou plage
                except ValueError:
                    pass

            title = s.get("title", "Inconnu")
            year = s.get("year", "")
            series_key = f"{title} ({year})" if year else title

            dest = s.get("symlink_destination") or s["destination"]
            season_dir = dest.parent.name  # ex: "Saison 01"

            if series_type not in type_groups:
                type_groups[series_type] = {}
            if letter not in type_groups[series_type]:
                type_groups[series_type][letter] = {}
            if series_key not in type_groups[series_type][letter]:
                type_groups[series_type][letter][series_key] = {}
            if season_dir not in type_groups[series_type][letter][series_key]:
                type_groups[series_type][letter][series_key][season_dir] = []
            type_groups[series_type][letter][series_key][season_dir].append(s)

        # Afficher par type, lettre, serie
        for series_type in sorted(type_groups.keys()):
            type_branch = tree.add(f"[bold magenta]Séries/{series_type}/[/bold magenta]")

            for letter in sorted(type_groups[series_type].keys()):
                letter_branch = type_branch.add(f"[magenta]{letter}/[/magenta]")
                for series_name in sorted(type_groups[series_type][letter].keys()):
                    series_sub = letter_branch.add(f"[magenta]{series_name}/[/magenta]")
                    for season in sorted(type_groups[series_type][letter][series_name].keys()):
                        season_sub = series_sub.add(f"[dim]{season}/[/dim]")
                        episodes = type_groups[series_type][letter][series_name][season]
                        # Trier par numero d'episode
                        episodes.sort(key=lambda e: e["new_filename"])
                        for ep in episodes:
                            new_name = ep["new_filename"]
                        season_sub.add(f"[green]{new_name}[/green]")

    console.print(tree)

from src.adapters.cli.validation import (
    ConflictResolution,
    console,
    determine_is_series,
    display_batch_summary,
    display_similar_content_conflict,
    execute_batch_transfer,
    prompt_conflict_resolution,
    validation_loop,
)
from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.auto_validator import auto_validate_files, ValidationResult
from src.adapters.cli.batch_builder import build_transfers_batch
from src.services.transferer import ExistingFileInfo, SimilarContentInfo
from src.container import Container
from src.core.entities.media import Episode, Movie, Series
from src.core.entities.video import ValidationStatus
from src.utils.helpers import parse_candidate


class MediaFilter(str, Enum):
    """Filtre par type de media."""

    ALL = "all"
    MOVIES = "movies"
    SERIES = "series"


# Application Typer pour les commandes validate
validate_app = typer.Typer(
    name="validate",
    help="Commandes de validation des fichiers video",
    rich_markup_mode="rich",
)


@validate_app.command("auto")
def validate_auto() -> None:
    """Valide automatiquement les fichiers avec score >= 85% et candidat unique."""
    asyncio.run(_validate_auto_async())


@with_container()
async def _validate_auto_async(container) -> None:
    """Implementation async de la validation automatique."""
    service = container.validation_service()
    pending_list = service.list_pending()

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente de validation.[/yellow]")
        return

    auto_count = 0
    for pending in pending_list:
        result = await service.process_auto_validation(pending)
        if result.auto_validated:
            auto_count += 1
            filename = (
                result.video_file.filename if result.video_file else "Fichier inconnu"
            )
            console.print(f"[green]Auto-valide:[/green] {filename}")

    console.print(f"\n[bold]{auto_count}[/bold] fichier(s) valide(s) automatiquement.")


@validate_app.command("manual")
def validate_manual() -> None:
    """Lance la validation manuelle interactive pour les fichiers en attente."""
    asyncio.run(_validate_manual_async())


@with_container()
async def _validate_manual_async(container) -> None:
    """Implementation async de la validation manuelle."""
    service = container.validation_service()
    tmdb_client = container.tmdb_client()
    pending_list = service.list_pending()

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente de validation manuelle.[/yellow]")
        return

    # Etape 1: Auto-validation par score et duree (delegue a auto_validator)
    result: ValidationResult = await auto_validate_files(pending_list, service, tmdb_client)

    if not result.remaining:
        console.print(
            f"[bold]{len(result.auto_validated)}[/bold] fichier(s) valide(s) automatiquement."
        )
        return

    # Etape 2: Validation manuelle pour les fichiers restants
    console.print(
        f"[bold]{len(result.remaining)}[/bold] fichier(s) restant(s) a valider manuellement.\n"
    )

    validated = []
    auto_in_manual = 0
    for pending in result.remaining:
        # Auto-validation si un seul candidat avec score >= 85%
        if service.should_auto_validate(service._parse_candidates(pending.candidates)):
            candidates = service._parse_candidates(pending.candidates)
            candidate = candidates[0]
            details = await service.validate_candidate(pending, candidate)
            validated.append({"pending": pending, "details": details})
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(
                f"[green]Auto:[/green] {filename} -> {details.title} ({candidate.score:.0f}%)"
            )
            auto_in_manual += 1
            continue

        result_loop = await validation_loop(pending, service)

        if result_loop == "quit":
            console.print("[yellow]Validation interrompue.[/yellow]")
            break
        elif result_loop == "trash":
            service.reject_pending(pending)
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Corbeille:[/red] {filename}")
        elif result_loop is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[yellow]Passe:[/yellow] {filename}")
        else:
            # result_loop est le SearchResult du candidat selectionne
            candidate = result_loop
            details = await service.validate_candidate(pending, candidate)
            validated.append({"pending": pending, "details": details})
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[green]Valide:[/green] {filename} -> {details.title}")

    total_validated = len(result.auto_validated) + len(validated)
    manual_count = len(validated) - auto_in_manual
    console.print(
        f"\n[bold]Resume:[/bold] {total_validated} fichier(s) valide(s) "
        f"({len(result.auto_validated) + auto_in_manual} auto, {manual_count} manuel)"
    )


@validate_app.command("batch")
def validate_batch() -> None:
    """Affiche et execute le batch de transferts pour les fichiers valides."""
    asyncio.run(_validate_batch_async())


@with_container()
async def _validate_batch_async(container) -> None:
    """Implementation async du batch de transferts."""
    from src.adapters.cli.batch_builder import build_transfers_batch
    from rich.prompt import Confirm

    config = container.config()
    service = container.validation_service()

    # Recuperer TransfererService avec les paths de config
    transferer = container.transferer_service(
        storage_dir=Path(config.storage_dir),
        video_dir=Path(config.video_dir),
    )

    # Recuperer les fichiers valides (status=VALIDATED)
    validated_list = service.list_validated()

    if not validated_list:
        console.print("[yellow]Aucun fichier valide pret pour transfert.[/yellow]")
        console.print("Utilisez 'validate auto' ou 'validate manual' d'abord.")
        return

    # Construire la liste des transferts en utilisant batch_builder
    storage_dir = Path(config.storage_dir)
    video_dir = Path(config.video_dir)

    transfers = await build_transfers_batch(
        validated_list,
        container,
        storage_dir,
        video_dir,
    )

    if not transfers:
        console.print("[yellow]Aucun transfert a effectuer.[/yellow]")
        return

    # Afficher le resume du batch
    console.print(f"\n[bold]Batch de transfert: {len(transfers)} fichier(s)[/bold]\n")
    display_batch_summary(transfers)

    # Demander confirmation
    if not Confirm.ask("\n[bold]Executer le transfert ?[/bold]", default=False):
        console.print("[yellow]Transfert annule.[/yellow]")
        return

    # Executer le batch
    console.print("\n[bold]Transfert en cours...[/bold]\n")
    results = await execute_batch_transfer(transfers, transferer)

    # Afficher le bilan
    success_count = sum(1 for r in results if r.get("success", False))
    error_count = len(results) - success_count

    console.print(f"\n[bold green]{success_count}[/bold green] fichier(s) transfere(s)")
    if error_count > 0:
        console.print(f"[bold red]{error_count}[/bold red] erreur(s)")
        for r in results:
            if not r.get("success", False):
                console.print(
                    f"  [red]- {r.get('filename', '?')}: {r.get('error', 'Erreur inconnue')}[/red]"
                )


# ============================================================================
# Commandes principales (process, pending)
# ============================================================================


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


@validate_app.command("file")
def validate_file(
    file_id: Annotated[str, typer.Argument(help="ID du fichier a valider")],
) -> None:
    """Valide un fichier specifique par son ID."""
    asyncio.run(_validate_file_async(file_id))


@with_container()
async def _validate_file_async(container, file_id: str) -> None:
    """Implementation async de validate file."""

    validation_svc = container.validation_service()

    # Chercher le pending par ID
    pend = validation_svc.get_pending_by_id(file_id)

    if pend is None:
        console.print(f"[red]Erreur:[/red] Fichier non trouve: {file_id}")
        raise typer.Exit(code=1)

    # Verifier le statut
    if pend.validation_status != ValidationStatus.PENDING:
        console.print(
            f"[yellow]Avertissement:[/yellow] "
            f"Ce fichier a deja le statut '{pend.validation_status.value}'"
        )

    # Lancer la boucle de validation interactive
    result = await validation_loop(pend, validation_svc)

    if result == "quit":
        console.print("[yellow]Validation annulee.[/yellow]")
    elif result == "trash":
        validation_svc.reject_pending(pend)
        console.print("[red]Fichier mis en corbeille.[/red]")
    elif result is None:
        console.print("[yellow]Fichier passe.[/yellow]")
    else:
        # result est le SearchResult du candidat selectionne
        candidate = result
        details = await validation_svc.validate_candidate(pend, candidate)
        console.print(f"[green]Fichier valide: {details.title}[/green]")


# ============================================================================
# Commande import
# ============================================================================


def import_library(
    source_dir: Annotated[
        Optional[Path],
        typer.Argument(help="Repertoire a importer (storage ou video selon mode)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la BDD"),
    ] = False,
    from_symlinks: Annotated[
        bool,
        typer.Option(
            "--from-symlinks",
            help="Import inverse: scanne les symlinks et resout leurs cibles",
        ),
    ] = False,
) -> None:
    """
    Importe une videotheque existante dans la base de donnees.

    Deux modes disponibles:

    - Mode standard (defaut): scanne les fichiers physiques dans storage_dir

    - Mode --from-symlinks: scanne les symlinks dans video_dir et resout leurs cibles.
      Enregistre a la fois le chemin du symlink ET le chemin du fichier physique.
    """
    asyncio.run(_import_library_async(source_dir, dry_run, from_symlinks))


@with_container()
async def _import_library_async(
    container, source_dir: Optional[Path], dry_run: bool, from_symlinks: bool
) -> None:
    """Implementation async de la commande import."""
    from src.services.importer import ImportDecision

    config = container.config()

    # Determiner le repertoire source selon le mode
    if source_dir is None:
        if from_symlinks:
            source_dir = Path(config.video_dir)
        else:
            source_dir = Path(config.storage_dir)

    # Verifier que le repertoire existe
    if not source_dir.exists():
        console.print(f"[red]Erreur:[/red] Repertoire introuvable: {source_dir}")
        raise typer.Exit(code=1)

    if dry_run:
        console.print("[yellow]Mode dry-run - aucune modification[/yellow]\n")

    # Creer le service d'import
    importer = container.importer_service(dry_run=dry_run)

    # Compteurs
    imported = 0
    skipped = 0
    updated = 0
    errors = 0

    # Afficher le mode
    if from_symlinks:
        console.print(
            f"[bold cyan]Import depuis les symlinks[/bold cyan]: {source_dir}\n"
        )
        console.print(
            "[dim]Les symlinks seront resolus vers leurs fichiers physiques cibles[/dim]\n"
        )
        scan_generator = importer.scan_from_symlinks(source_dir)
    else:
        console.print(f"[bold cyan]Import de la videotheque[/bold cyan]: {source_dir}\n")
        scan_generator = importer.scan_library(source_dir)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        import_task = progress.add_task("[cyan]Scan en cours...", total=None)

        for result in scan_generator:
            # Mettre a jour la description avec le nom du fichier
            progress.update(import_task, description=f"[cyan]{result.filename}")

            # Mettre a jour les compteurs
            if result.decision == ImportDecision.IMPORT:
                imported += 1
            elif result.decision == ImportDecision.SKIP_KNOWN:
                skipped += 1
            elif result.decision == ImportDecision.UPDATE_PATH:
                updated += 1
            elif result.decision == ImportDecision.ERROR:
                errors += 1
                console.print(
                    f"[red]Erreur:[/red] {result.filename}: {result.error_message}"
                )

        # Marquer comme termine
        progress.update(
            import_task,
            total=imported + skipped + updated + errors,
            completed=imported + skipped + updated + errors,
            description="[green]Termine",
        )

    # Afficher le resume final
    console.print("\n[bold]Resume de l'import:[/bold]")
    console.print(f"  [green]{imported}[/green] importe(s)")
    if updated > 0:
        console.print(f"  [blue]{updated}[/blue] mis a jour")
    console.print(f"  [yellow]{skipped}[/yellow] ignore(s)")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")


# ============================================================================
# Commande enrich
# ============================================================================


def enrich() -> None:
    """Enrichit les metadonnees des fichiers via API."""
    asyncio.run(_enrich_async())


@with_container()
async def _enrich_async(container) -> None:
    """Implementation async de la commande enrich."""

    enricher = container.enricher_service()

    # Recuperer les fichiers a enrichir
    pending = enricher.list_pending_enrichment()

    if not pending:
        console.print("[yellow]Aucun fichier a enrichir.[/yellow]")
        console.print("[dim]Tous les fichiers ont deja des candidats.[/dim]")
        return

    console.print(f"[bold cyan]Enrichissement API[/bold cyan]: {len(pending)} fichier(s)\n")

    with suppress_loguru():
        enriched_count = 0
        failed_count = 0

        for i, item in enumerate(pending, 1):
            filename = item.video_file.filename if item.video_file else "inconnu"

            # Enrichir ce fichier
            result = await enricher.enrich_batch(
                items=[item],
                progress_callback=None,
                advance_callback=None,
            )

            if result.enriched > 0:
                # Afficher en vert avec le nombre de candidats et le meilleur score
                if item.candidates:
                    best_score = item.candidates[0].get("score", 0) if item.candidates else 0
                    console.print(f"[dim]({i}/{len(pending)})[/dim] [green]{filename}[/green] ✓ {len(item.candidates)} candidat(s), score: {best_score:.0f}%")
                else:
                    console.print(f"[dim]({i}/{len(pending)})[/dim] [green]{filename}[/green] ✓")
                enriched_count += 1
            else:
                # Afficher en rouge
                console.print(f"[dim]({i}/{len(pending)})[/dim] [red]{filename}[/red] ✗")
                failed_count += 1

        # Afficher le resume
        console.print(f"\n[bold]Resume:[/bold] [green]{enriched_count}[/green] enrichi(s), [red]{failed_count}[/red] echec(s)")


# ============================================================================
# Commande populate-movies
# ============================================================================


def populate_movies(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a traiter (0 = illimite)",
        ),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
) -> None:
    """Cree/met a jour les films dans la table movies depuis les validations."""
    asyncio.run(_populate_movies_async(limit, dry_run))


@with_container()
async def _populate_movies_async(container, limit: int, dry_run: bool) -> None:
    """Implementation async de la commande populate-movies."""
    from src.core.entities.media import Movie
    from src.core.entities.video import ValidationStatus

    # Recuperer les repositories
    pending_repo = container.pending_validation_repository()
    movie_repo = container.movie_repository()
    tmdb_client = container.tmdb_client()

    with suppress_loguru():
        # Lister les validations validees avec un tmdb_id
        # limit=0 signifie illimite
        fetch_limit = 0 if limit == 0 else limit * 2  # Marge pour filtrage
        all_validated = pending_repo.list_validated(fetch_limit)
        # Filtrer pour ne garder que les films (source=tmdb dans les candidats)
        validated_movies = []
        for p in all_validated:
            if not p.video_file or not p.candidates:
                continue
            # Verifier si c'est un film (source=tmdb)
            first_candidate = p.candidates[0] if p.candidates else None
            if first_candidate:
                source = first_candidate.get("source") if isinstance(first_candidate, dict) else getattr(first_candidate, "source", None)
                if source == "tmdb":
                    validated_movies.append(p)
            if limit > 0 and len(validated_movies) >= limit:
                break

        if not validated_movies:
            console.print("[yellow]Aucun film valide a traiter.[/yellow]")
            console.print("[dim]Utilisez 'process' ou 'pending' pour valider des films.[/dim]")
            return

        console.print(
            f"[bold cyan]Population de la table movies[/bold cyan]: {len(validated_movies)} film(s)\n"
        )

        if dry_run:
            console.print("[yellow]Mode dry-run - aucune modification[/yellow]\n")

        created = 0
        updated = 0
        errors = 0

        for i, pending in enumerate(validated_movies, 1):
            tmdb_id = pending.selected_candidate_id
            filename = pending.video_file.filename if pending.video_file else "?"

            try:
                # Verifier si le film existe deja avec ce tmdb_id
                existing = movie_repo.get_by_tmdb_id(int(tmdb_id))

                if existing:
                    console.print(f"[dim]({i}/{len(validated_movies)})[/dim] {filename} - deja en base")
                    updated += 1
                    continue

                # Recuperer les details depuis TMDB
                details = await tmdb_client.get_details(tmdb_id)

                if not details:
                    console.print(f"[dim]({i}/{len(validated_movies)})[/dim] [red]{filename}[/red] - TMDB introuvable")
                    errors += 1
                    continue

                # Creer l'entite Movie avec toutes les infos
                movie = Movie(
                    tmdb_id=int(tmdb_id),
                    title=details.title,
                    original_title=details.original_title,
                    year=details.year,
                    genres=details.genres or (),
                    duration_seconds=details.duration_seconds,
                    overview=details.overview,
                    poster_path=details.poster_url,
                    vote_average=details.vote_average,
                    vote_count=details.vote_count,
                )

                if not dry_run:
                    movie_repo.save(movie)

                console.print(f"[dim]({i}/{len(validated_movies)})[/dim] [green]{filename}[/green] -> {details.title} ({details.year})")
                created += 1

                # Rate limiting
                await asyncio.sleep(0.25)

            except Exception as e:
                console.print(f"[dim]({i}/{len(validated_movies)})[/dim] [red]{filename}[/red] - Erreur: {e}")
                errors += 1

        # Resume
        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{created}[/green] film(s) cree(s)")
        console.print(f"  [yellow]{updated}[/yellow] deja en base")
        if errors > 0:
            console.print(f"  [red]{errors}[/red] erreur(s)")

        if not dry_run and created > 0:
            console.print("\n[dim]Utilisez 'enrich-ratings' pour enrichir les notes TMDB.[/dim]")

        if tmdb_client:
            await tmdb_client.close()


# ============================================================================
# Commande enrich-ratings
# ============================================================================


def enrich_ratings(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 100,
) -> None:
    """Enrichit les notes TMDB (vote_average, vote_count) pour les films sans notes."""
    asyncio.run(_enrich_ratings_async(limit))


@with_container()
async def _enrich_ratings_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-ratings."""
    from src.services.ratings_enricher import RatingsEnricherService

    # Creer le service d'enrichissement des notes
    movie_repo = container.movie_repository()
    tmdb_client = container.tmdb_client()

    service = RatingsEnricherService(
        movie_repo=movie_repo,
        tmdb_client=tmdb_client,
    )

    # Verifier d'abord combien de films sont a enrichir
    movies_to_enrich = movie_repo.list_without_ratings(limit)

    if not movies_to_enrich:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja leurs notes TMDB.[/dim]")
        return

    console.print(
        f"[bold cyan]Enrichissement des notes TMDB[/bold cyan]: {len(movies_to_enrich)} film(s)\n"
    )

    with suppress_loguru():
        stats = await service.enrich_ratings(limit=limit, rate_limit_seconds=0.25)

        # Afficher le resume
        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s)")
        if stats.skipped > 0:
            console.print(f"  [yellow]{stats.skipped}[/yellow] ignore(s)")


def enrich_imdb_ids(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 100,
) -> None:
    """Recupere les imdb_id depuis TMDB pour les films sans cette information."""
    asyncio.run(_enrich_imdb_ids_async(limit))


@with_container()
async def _enrich_imdb_ids_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-imdb-ids."""
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

    from src.services.imdb_id_enricher import ImdbIdEnricherService, EnrichmentResult, ProgressInfo

    # Creer le service d'enrichissement des imdb_id
    movie_repo = container.movie_repository()
    tmdb_client = container.tmdb_client()

    service = ImdbIdEnricherService(
        movie_repo=movie_repo,
        tmdb_client=tmdb_client,
    )

    # Verifier d'abord combien de films sont a enrichir
    movies_to_enrich = movie_repo.list_without_imdb_id(limit)

    if not movies_to_enrich:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja leur imdb_id.[/dim]")
        return

    total = len(movies_to_enrich)
    console.print(
        f"[bold cyan]Enrichissement des imdb_id[/bold cyan]: {total} film(s)\n"
    )

    with suppress_loguru():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("[cyan]Enrichissement...", total=total)

            def on_progress(info: ProgressInfo) -> None:
                """Callback de progression."""
                # Mettre a jour la barre de progression
                progress.update(task, completed=info.current)

                # Afficher le resultat pour chaque film
                year_str = f" ({info.movie_year})" if info.movie_year else ""
                title = f"{info.movie_title}{year_str}"

                if info.result == EnrichmentResult.SUCCESS:
                    progress.console.print(f"  [green]✓[/green] {title} → {info.imdb_id}")
                elif info.result == EnrichmentResult.FAILED:
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")
                elif info.result == EnrichmentResult.NOT_FOUND:
                    progress.console.print(f"  [yellow]?[/yellow] {title} - pas d'imdb_id sur TMDB")
                elif info.result == EnrichmentResult.SKIPPED:
                    progress.console.print(f"  [dim]-[/dim] {title} - ignore (sans tmdb_id)")

            stats = await service.enrich_imdb_ids(
                limit=limit,
                rate_limit_seconds=0.25,
                on_progress=on_progress,
            )

        # Afficher le resume
        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s) API")
        if stats.not_found > 0:
            console.print(f"  [yellow]{stats.not_found}[/yellow] sans imdb_id sur TMDB")
        if stats.skipped > 0:
            console.print(f"  [dim]{stats.skipped}[/dim] ignore(s) (sans tmdb_id)")


# ============================================================================
# Commandes IMDb
# ============================================================================

# Application Typer pour les commandes IMDb
imdb_app = typer.Typer(
    name="imdb",
    help="Commandes de gestion des datasets IMDb",
    rich_markup_mode="rich",
)


@imdb_app.command("import")
def imdb_import(
    force: Annotated[
        bool,
        typer.Option(
            "--force", "-f",
            help="Force le re-telechargement meme si le fichier est recent",
        ),
    ] = False,
) -> None:
    """Telecharge et importe les notes IMDb depuis les datasets publics."""
    asyncio.run(_imdb_import_async(force))


@with_container()
async def _imdb_import_async(container, force: bool) -> None:
    """Implementation async de la commande imdb import."""
    from rich.status import Status

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    # Repertoire de cache pour les datasets
    cache_dir = Path(".cache/imdb")
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = container.session()
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    with suppress_loguru():
        ratings_file = cache_dir / "title.ratings.tsv.gz"

        # Verifier si un telechargement est necessaire
        if force or importer.needs_update(ratings_file, max_age_days=7):
            with Status("[cyan]Telechargement du dataset title.ratings...", console=console):
                ratings_file = await importer.download_dataset("title.ratings")
            console.print("[green]Telechargement termine.[/green]")
        else:
            console.print("[yellow]Dataset recent, pas de telechargement necessaire.[/yellow]")
            console.print("[dim]Utilisez --force pour forcer le re-telechargement.[/dim]")

        # Import en base
        with Status("[cyan]Import des notes en base...", console=console):
            stats = importer.import_ratings(ratings_file)

        console.print(f"\n[bold]Resume de l'import:[/bold]")
        console.print(f"  [green]{stats.imported:,}[/green] notes importees")
        if stats.errors > 0:
            console.print(f"  [red]{stats.errors:,}[/red] erreurs")


@imdb_app.command("sync")
def imdb_sync(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a synchroniser",
        ),
    ] = 100,
) -> None:
    """Synchronise les notes IMDb avec les films en base."""
    asyncio.run(_imdb_sync_async(limit))


@with_container()
async def _imdb_sync_async(container, limit: int) -> None:
    """Implementation async de la commande imdb sync."""
    from loguru import logger as loguru_logger

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    # Recuperer les repositories
    movie_repo = container.movie_repository()
    session = container.session()

    cache_dir = Path(".cache/imdb")
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    # Desactiver les logs loguru pendant l'affichage
    loguru_logger.disable("src")

    try:
        # Lister les films avec imdb_id mais sans imdb_rating
        from sqlmodel import select
        from src.infrastructure.persistence.models import MovieModel

        statement = (
            select(MovieModel)
            .where(MovieModel.imdb_id.isnot(None))
            .where(MovieModel.imdb_rating.is_(None))
            .limit(limit)
        )
        movies_to_sync = session.exec(statement).all()

        if not movies_to_sync:
            console.print("[yellow]Aucun film a synchroniser.[/yellow]")
            console.print("[dim]Tous les films avec imdb_id ont deja leurs notes IMDb.[/dim]")
            return

        console.print(f"[bold cyan]Synchronisation IMDb[/bold cyan]: {len(movies_to_sync)} film(s)\n")

        synced = 0
        not_found = 0

        for movie in movies_to_sync:
            rating = importer.get_rating(movie.imdb_id)

            if rating:
                movie.imdb_rating = rating[0]
                movie.imdb_votes = rating[1]
                session.add(movie)
                synced += 1
                console.print(f"  [green]✓[/green] {movie.title} - {rating[0]}/10 ({rating[1]:,} votes)")
            else:
                not_found += 1
                console.print(f"  [yellow]?[/yellow] {movie.title} - non trouve dans le cache IMDb")

        session.commit()

        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{synced}[/green] synchronise(s)")
        if not_found > 0:
            console.print(f"  [yellow]{not_found}[/yellow] non trouve(s)")

    finally:
        loguru_logger.enable("src")


@imdb_app.command("stats")
def imdb_stats() -> None:
    """Affiche les statistiques du cache IMDb local."""
    asyncio.run(_imdb_stats_async())


@with_container()
async def _imdb_stats_async(container) -> None:
    """Implementation async de la commande imdb stats."""
    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    cache_dir = Path(".cache/imdb")
    session = next(container.session.provider())
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    stats = importer.get_stats()

    console.print("[bold cyan]Statistiques du cache IMDb[/bold cyan]\n")
    console.print(f"  Nombre d'enregistrements: [bold]{stats['count']:,}[/bold]")
    if stats['last_updated']:
        console.print(f"  Derniere mise a jour: [bold]{stats['last_updated']}[/bold]")
    else:
        console.print("  [yellow]Aucune donnee importee.[/yellow]")
        console.print("  [dim]Utilisez 'cineorg imdb import' pour importer les notes.[/dim]")


# ============================================================================
# Commande repair-links
# ============================================================================


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
) -> None:
    """
    Detecte et repare les symlinks casses.

    Recherche floue basee sur la similarite des titres de films.

    Exemples:
      cineorg repair-links                    # Scan tout video_dir
      cineorg repair-links /path/to/Films     # Scan un repertoire specifique
      cineorg repair-links --auto             # Reparation automatique (score >= 90%)
      cineorg repair-links --auto --dry-run   # Simulation sans modification
    """
    asyncio.run(_repair_links_async(scan_dir, auto, min_score, dry_run))


async def _repair_links_async(
    scan_dir: Optional[Path], auto_repair: bool, min_score: float, dry_run: bool
) -> None:
    """Implementation async de la commande repair-links."""
    from loguru import logger as loguru_logger
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
    )
    from rich.status import Status

    from src.adapters.cli.repair_helpers import (
        CustomSearch,
        CandidateDisplay,
        RepairSummary,
        display_broken_link_info,
        extract_series_name,
    )
    from src.services.integrity import RepairAction, RepairActionType

    container = Container()
    config = container.config()
    container.database.init()

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
        with Status(f"[cyan]Indexation du stockage ({storage_dir})...", console=console) as status:
            def update_status(count: int, msg: str) -> None:
                status.update(f"[cyan]Indexation du stockage: {count} fichiers...")

            file_count = repair.build_file_index(progress_callback=update_status)

        console.print(f"[bold cyan]Index:[/bold cyan] {file_count} fichiers dans {storage_dir}")

        mode_label = "[dim](dry-run)[/dim] " if dry_run else ""
        console.print(f"\n{mode_label}[dim]Recherche progressive: genre -> type -> base[/dim]\n")

        if auto_repair:
            console.print("[yellow]Mode automatique: reparation si score >= 90%[/yellow]\n")

        actions: list[RepairAction] = []
        auto_repaired = 0
        no_match_count = 0

        # Mode automatique avec barre de progression
        if auto_repair:
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
                    progress.update(task, description=f"[cyan]{short_name}")

                    # Chercher des cibles possibles avec recherche floue
                    targets_with_scores = repair.find_possible_targets(link, min_score=min_score)

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

            # Afficher le resume des reparations auto
            console.print(f"\n[bold]Reparations automatiques:[/bold]")
            console.print(f"  [green]{auto_repaired}[/green] repare(s) (score >= 90%)")
            console.print(f"  [yellow]{len(broken) - auto_repaired - no_match_count}[/yellow] ignore(s) (score < 90%)")
            console.print(f"  [red]{no_match_count}[/red] sans candidat")

        # Mode interactif
        else:
            # Suivi des echecs par serie pour proposer d'ignorer toute la serie
            series_failures: dict[str, int] = {}  # {nom_serie: nb_echecs}
            skipped_series: set[str] = set()  # Series a ignorer completement

            for i, link in enumerate(broken, 1):
                # Verifier si cette serie doit etre ignoree
                series_name = extract_series_name(link)
                if series_name and series_name in skipped_series:
                    actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                    continue

                # Afficher les infos du lien
                console.print(f"\n[dim]({i}/{len(broken)})[/dim]")

                # Chercher des cibles possibles avec recherche floue
                with console.status(f"[cyan]Recherche de candidats pour {link.name}..."):
                    targets_with_scores = repair.find_possible_targets(link, min_score=min_score)

                # Afficher le panel avec les infos du lien
                display_broken_link_info(console, link)

                # Pagination des candidats
                page_start = 0

                if targets_with_scores:
                    # Auto-reparation si score = 100%
                    if targets_with_scores[0][1] >= 100:
                        best_target, best_score = targets_with_scores[0]
                        console.print(f"\n[green]Match parfait (100%)[/green]: {best_target.name}")
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
                            if series_name and series_name in series_failures:
                                series_failures[series_name] = 0
                            console.print(f"[green]✓ Auto-repare -> {best_target.name}[/green]\n")
                        else:
                            console.print("[red]Echec de la reparation automatique[/red]\n")
                        continue  # Passer au symlink suivant

                    console.print(f"\n[green]{len(targets_with_scores)}[/green] cible(s) possible(s):")
                    CandidateDisplay.display(console, targets_with_scores, page_start)

                # Boucle pour gerer la pagination et recherche par titre
                while True:
                    # Prompt interactif avec raccourcis
                    valid_choices = {"r", "s", "i", "q", "t"}  # t = rechercher par titre
                    has_more = CandidateDisplay.has_more(targets_with_scores, page_start)
                    if has_more:
                        valid_choices.add("p")

                    if targets_with_scores:
                        default = "r" if targets_with_scores[0][1] >= 70 else "i"
                        # Affichage propre des options
                        options = "[green]r[/green]=reparer  [yellow]s[/yellow]=supprimer  [dim]i[/dim]=ignorer  [red]q[/red]=quitter  [magenta]t[/magenta]=titre"
                        if has_more:
                            options += "  [cyan]p[/cyan]=plus"
                    else:
                        default = "i"
                        options = "[yellow]s[/yellow]=supprimer  [dim]i[/dim]=ignorer  [red]q[/red]=quitter  [magenta]t[/magenta]=titre"

                    console.print(f"\n{options}")
                    choice = input(f"Action [{default}]: ").strip().lower() or default

                    # Valider le choix
                    if choice not in valid_choices:
                        console.print(f"[red]Choix invalide. Utilisez: {', '.join(sorted(valid_choices))}[/red]")
                        continue

                    # Recherche par titre personnalise
                    if choice == "t":
                        custom_title = input("Titre a rechercher: ").strip()
                        if custom_title:
                            console.print(f"[cyan]Recherche de '{custom_title}'...[/cyan]")

                            # Utiliser CustomSearch pour la recherche
                            custom_results = CustomSearch.search(repair, custom_title, link, min_score)

                            if custom_results:
                                targets_with_scores = custom_results
                                page_start = 0
                                media_label = "films" if "/films/" in str(link).lower() else "séries" if "/séries/" in str(link).lower() or "/series/" in str(link).lower() else "tous"
                                console.print(f"\n[green]{len(targets_with_scores)}[/green] resultat(s) pour '{custom_title}' ({media_label}):")
                                CandidateDisplay.display(console, targets_with_scores, page_start)
                            else:
                                console.print(f"[red]Aucun resultat pour '{custom_title}'[/red]")
                        continue

                    # Gerer la pagination
                    if choice == "p":
                        page_start += CandidateDisplay.PAGE_SIZE
                        console.print("")
                        CandidateDisplay.display(console, targets_with_scores, page_start)
                        continue
                    else:
                        break

                if choice == "q":
                    console.print("[yellow]Reparation interrompue.[/yellow]")
                    break

                elif choice == "i":
                    actions.append(
                        RepairAction(link=link, action=RepairActionType.SKIPPED)
                    )
                    console.print("[dim]Ignore[/dim]")

                    # Compter les echecs pour cette serie
                    if series_name:
                        series_failures[series_name] = series_failures.get(series_name, 0) + 1

                        # Apres 3 echecs, proposer d'ignorer toute la serie
                        if series_failures[series_name] == 3:
                            # Compter combien d'episodes restants pour cette serie
                            remaining = sum(
                                1 for future_link in broken[i:]
                                if extract_series_name(future_link) == series_name
                            )
                            if remaining > 0:
                                console.print(
                                    f"\n[yellow]3 echecs consecutifs pour '{series_name}'.[/yellow]"
                                )
                                skip_all = input(
                                    f"Ignorer les {remaining} episode(s) restant(s) de cette serie ? (o/n) [n]: "
                                ).strip().lower()
                                if skip_all == "o" or skip_all == "oui":
                                    skipped_series.add(series_name)
                                    console.print(f"[dim]Serie '{series_name}' ignoree.[/dim]")
                    console.print("")

                elif choice == "s":
                    if dry_run:
                        actions.append(
                            RepairAction(link=link, action=RepairActionType.ORPHANED)
                        )
                        console.print(f"[cyan](dry-run)[/cyan] Deplacement vers orphans\n")
                    else:
                        dest = repair.move_to_orphans(link)
                        if dest:
                            actions.append(
                                RepairAction(link=link, action=RepairActionType.ORPHANED)
                            )
                            console.print(f"[yellow]Deplace vers orphans[/yellow]\n")
                        else:
                            console.print("[red]Echec du deplacement[/red]\n")

                elif choice == "r":
                    if not targets_with_scores:
                        console.print("[red]Aucune cible trouvee[/red]\n")
                        actions.append(
                            RepairAction(link=link, action=RepairActionType.SKIPPED)
                        )
                        continue

                    # Selection de la cible (tous les candidats disponibles)
                    max_choice = min(len(targets_with_scores), 15)  # Limite a 15
                    target_choice = input(f"Cible (1-{max_choice}, a=annuler) [1]: ").strip().lower() or "1"

                    if target_choice == "a" or target_choice == "annuler":
                        actions.append(
                            RepairAction(link=link, action=RepairActionType.SKIPPED)
                        )
                        console.print("[dim]Annule[/dim]\n")
                    else:
                        try:
                            target_idx = int(target_choice) - 1
                            if target_idx < 0 or target_idx >= len(targets_with_scores):
                                console.print(f"[red]Choix invalide (1-{max_choice})[/red]\n")
                                actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                                continue
                        except ValueError:
                            console.print(f"[red]Choix invalide (1-{max_choice} ou 'a')[/red]\n")
                            actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                            continue
                        new_target, score = targets_with_scores[target_idx]

                        if dry_run:
                            success = True
                            console.print(f"[cyan](dry-run)[/cyan] Reparation: {new_target.name}\n")
                        else:
                            success = repair.repair_symlink(link, new_target)

                        if success:
                            actions.append(
                                RepairAction(
                                    link=link,
                                    action=RepairActionType.REPAIRED,
                                    new_target=new_target,
                                )
                            )
                            # Reinitialiser le compteur d'echecs pour cette serie
                            if series_name and series_name in series_failures:
                                series_failures[series_name] = 0
                            if not dry_run:
                                console.print(f"[green]Repare -> {new_target.name}[/green]\n")
                        else:
                            console.print("[red]Echec de la reparation[/red]\n")

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


# ============================================================================
# Commande consolidate
# ============================================================================


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
    from rich.table import Table

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

    # Compter les accessibles et inaccessibles
    accessible = [s for s in symlinks if s.status == ConsolidationStatus.ACCESSIBLE]
    inaccessible = [s for s in symlinks if s.status == ConsolidationStatus.INACCESSIBLE]

    if inaccessible:
        console.print(f"\n[yellow]Attention:[/yellow] {len(inaccessible)} fichiers inaccessibles")
        console.print("[dim]Volumes non montes ou permissions insuffisantes[/dim]")

    # Si pas de consolidation demandee, afficher quelques exemples
    if not do_consolidate:
        console.print("\n[dim]Exemples de symlinks externes:[/dim]")
        for s in symlinks[:5]:
            status_icon = "[green]✓[/green]" if s.status == ConsolidationStatus.ACCESSIBLE else "[red]✗[/red]"
            console.print(f"  {status_icon} {s.symlink_path.name}")
            console.print(f"    [dim]-> {s.target_path}[/dim]")

        if len(symlinks) > 5:
            console.print(f"  [dim]... et {len(symlinks) - 5} autres[/dim]")

        console.print(f"\n[cyan]Pour rapatrier les fichiers accessibles:[/cyan]")
        console.print(f"  cineorg consolidate --consolidate")
        return

    # Effectuer la consolidation
    if not accessible:
        console.print("\n[yellow]Aucun fichier accessible a rapatrier.[/yellow]")
        return

    mode_label = "[dim](dry-run)[/dim] " if dry_run else ""
    console.print(f"\n[bold cyan]{mode_label}Rapatriement de {len(accessible)} fichiers...[/bold cyan]\n")

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
                console.print(f"[red]Erreur:[/red] {symlink.symlink_path.name}: {result.error_message}")

            progress.advance(task)

        progress.update(task, description="[green]Termine")

    # Resume
    console.print(f"\n[bold]Resume:[/bold]")
    console.print(f"  [green]{consolidated}[/green] fichier(s) rapatrie(s)")
    if errors:
        console.print(f"  [red]{errors}[/red] erreur(s)")
    console.print(f"  [yellow]{len(inaccessible)}[/yellow] inaccessible(s)")


# ============================================================================
# Commande check
# ============================================================================


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


# ============================================================================
# Commande cleanup
# ============================================================================


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
    from rich.table import Table

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
        _display_cleanup_report(report)

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


def _display_cleanup_report(report: "CleanupReport") -> None:
    """Affiche le rapport de cleanup sous forme de tableau Rich."""
    from rich.table import Table

    table = Table(title="Rapport de nettoyage", show_header=True)
    table.add_column("Categorie", style="cyan")
    table.add_column("Nombre", justify="right")
    table.add_column("Details", style="dim")

    table.add_row(
        "Symlinks casses",
        str(len(report.broken_symlinks)),
        f"{sum(1 for b in report.broken_symlinks if b.best_candidate)} reparables"
        if report.broken_symlinks else "",
    )
    table.add_row(
        "Symlinks mal places",
        str(len(report.misplaced_symlinks)),
        "",
    )
    table.add_row(
        "Symlinks dupliques",
        str(len(report.duplicate_symlinks)),
        ", ".join(
            f"{d.keep.name}" for d in report.duplicate_symlinks[:3]
        ) if report.duplicate_symlinks else "",
    )
    table.add_row(
        "Repertoires surcharges",
        str(len(report.oversized_dirs)),
        ", ".join(f"{p.parent_dir.name} ({p.current_count})" for p in report.oversized_dirs[:3])
        if report.oversized_dirs else "",
    )
    table.add_row(
        "Repertoires vides",
        str(len(report.empty_dirs)),
        "",
    )

    if report.not_in_db_count > 0:
        table.add_row(
            "Non references en BDD",
            str(report.not_in_db_count),
            "(ignores)",
        )

    console.print(table)

    # Arbres detailles par categorie
    if report.broken_symlinks:
        _display_broken_symlinks_tree(report)
    if report.misplaced_symlinks:
        _display_misplaced_symlinks_tree(report)
    if report.duplicate_symlinks:
        _display_duplicate_symlinks_tree(report)
    if report.oversized_dirs:
        _display_oversized_dirs_tree(report)
    if report.empty_dirs:
        _display_empty_dirs_tree(report)


def _rel_parent(path: Path, video_dir: Path) -> str:
    """Chemin parent relatif a video_dir, ou absolu si hors scope."""
    try:
        return str(path.parent.relative_to(video_dir))
    except ValueError:
        return str(path.parent)


def _display_broken_symlinks_tree(report: "CleanupReport") -> None:
    """Affiche l'arbre detaille des symlinks casses groupes par repertoire."""
    from collections import defaultdict

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for b in report.broken_symlinks:
        groups[_rel_parent(b.symlink_path, report.video_dir)].append(b)

    tree = Tree(f"[bold red]Symlinks casses ({len(report.broken_symlinks)})[/bold red]")

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for b in sorted(groups[dir_path], key=lambda x: x.symlink_path.name):
            name = b.symlink_path.name
            target_name = b.original_target.name if b.original_target != Path("") else "?"

            if b.best_candidate and b.candidate_score >= 90.0:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [green]reparable ({b.candidate_score:.0f}%): {b.best_candidate.name}[/green]"
                )
            elif b.best_candidate:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [yellow]candidat ({b.candidate_score:.0f}%): {b.best_candidate.name}[/yellow]"
                )
            else:
                label = (
                    f"[red]{name}[/red] -> [dim strikethrough]{target_name}[/dim strikethrough]"
                    f"  [dim]aucun candidat[/dim]"
                )
            dir_branch.add(label)

    console.print(tree)


def _display_misplaced_symlinks_tree(report: "CleanupReport") -> None:
    """Affiche l'arbre des symlinks mal places avec deplacement prevu."""
    from collections import defaultdict

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for m in report.misplaced_symlinks:
        groups[_rel_parent(m.symlink_path, report.video_dir)].append(m)

    tree = Tree(
        f"[bold yellow]Symlinks mal places ({len(report.misplaced_symlinks)})[/bold yellow]"
    )

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for m in sorted(groups[dir_path], key=lambda x: x.symlink_path.name):
            try:
                expected_rel = str(m.expected_dir.relative_to(report.video_dir))
            except ValueError:
                expected_rel = str(m.expected_dir)
            dir_branch.add(
                f"[yellow]{m.symlink_path.name}[/yellow]"
                f"  -> [green]{expected_rel}/[/green]"
            )

    console.print(tree)


def _display_duplicate_symlinks_tree(report: "CleanupReport") -> None:
    """Affiche l'arbre des symlinks dupliques avec conservation/suppression."""
    from collections import defaultdict

    console.print()

    groups: dict[str, list] = defaultdict(list)
    for d in report.duplicate_symlinks:
        try:
            rel_dir = str(d.directory.relative_to(report.video_dir))
        except ValueError:
            rel_dir = str(d.directory)
        groups[rel_dir].append(d)

    total_remove = sum(len(d.remove) for d in report.duplicate_symlinks)
    tree = Tree(
        f"[bold magenta]Symlinks dupliques ({total_remove} a supprimer)[/bold magenta]"
    )

    for dir_path in sorted(groups.keys()):
        dir_branch = tree.add(f"[cyan]{dir_path}/[/cyan]")
        for d in groups[dir_path]:
            target_branch = dir_branch.add(
                f"[dim]cible: {d.target_path.name}[/dim]"
            )
            target_branch.add(f"[green]conserver: {d.keep.name}[/green]")
            for r in sorted(d.remove, key=lambda p: p.name):
                target_branch.add(f"[red]supprimer: {r.name}[/red]")

    console.print(tree)


def _display_oversized_dirs_tree(report: "CleanupReport") -> None:
    """Affiche l'arbre des repertoires surcharges avec le plan de subdivision."""
    console.print()

    tree = Tree(
        f"[bold blue]Repertoires surcharges ({len(report.oversized_dirs)})[/bold blue]"
    )

    for plan in report.oversized_dirs:
        try:
            rel_dir = str(plan.parent_dir.relative_to(report.video_dir))
        except ValueError:
            rel_dir = str(plan.parent_dir)

        plan_branch = tree.add(
            f"[cyan]{rel_dir}/[/cyan]  [dim]{plan.current_count} items (max {plan.max_allowed})[/dim]"
        )
        for start, end in plan.ranges:
            range_label = f"{start}-{end}"
            count = sum(
                1 for _, dst in plan.items_to_move
                if dst.parent.name == range_label
            )
            plan_branch.add(f"[green]{range_label}/[/green]  [dim]({count} items)[/dim]")

        # Afficher les items hors plage avec leur destination
        if hasattr(plan, "out_of_range_items") and plan.out_of_range_items:
            nb_out = len(plan.out_of_range_items)
            out_branch = plan_branch.add(
                f"[yellow]Hors plage -> transfert ({nb_out} items)[/yellow]"
            )
            max_display = 10
            for src, dst in plan.out_of_range_items[:max_display]:
                try:
                    dest_rel = str(dst.parent.relative_to(report.video_dir))
                except ValueError:
                    dest_rel = dst.parent.name
                out_branch.add(
                    f"[yellow]{src.name}[/yellow] [dim]-> {dest_rel}/[/dim]"
                )
            if nb_out > max_display:
                out_branch.add(f"[dim]... et {nb_out - max_display} autres[/dim]")

    console.print(tree)


def _display_empty_dirs_tree(report: "CleanupReport") -> None:
    """Affiche l'arbre des repertoires vides."""
    console.print()

    tree = Tree(
        f"[bold dim]Repertoires vides ({len(report.empty_dirs)})[/bold dim]"
    )

    for d in sorted(report.empty_dirs):
        try:
            rel = str(d.relative_to(report.video_dir))
        except ValueError:
            rel = str(d)
        tree.add(f"[dim]{rel}/[/dim]")

    console.print(tree)
