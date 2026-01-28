"""
Commandes Typer pour la validation des fichiers video.

Ce module fournit les commandes CLI:
- process: Workflow complet (scan -> matching -> validation -> transfert)
- pending: Liste des fichiers en attente de validation
- validate auto: Validation automatique (score >= 85% et candidat unique)
- validate manual: Validation manuelle interactive
- validate batch: Execution du batch de transferts pour les fichiers valides
- validate file: Validation d'un fichier specifique par ID
"""

import asyncio
import re
from enum import Enum
from pathlib import Path
from typing import Annotated

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

from src.core.value_objects.parsed_info import MediaType


# Pattern pour extraire saison/episode d'un nom de fichier
SERIES_INFO_PATTERN = re.compile(
    r"[Ss](\d{1,2})[Ee](\d{1,2})",  # S01E01, s1e1
    re.IGNORECASE
)


def _extract_series_info(filename: str) -> tuple[int, int]:
    """
    Extrait le numero de saison et d'episode d'un nom de fichier.

    Args:
        filename: Nom du fichier video

    Returns:
        Tuple (season_number, episode_number), defaut (1, 1) si non trouve
    """
    match = SERIES_INFO_PATTERN.search(filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1, 1

from src.adapters.cli.validation import (
    console,
    determine_is_series,
    display_batch_summary,
    execute_batch_transfer,
    validation_loop,
)
from src.container import Container
from src.core.entities.media import Episode, Movie, Series
from src.core.entities.video import ValidationStatus


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


async def _validate_auto_async() -> None:
    """Implementation async de la validation automatique."""
    container = Container()
    await container.database.init()

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


async def _validate_manual_async() -> None:
    """Implementation async de la validation manuelle."""
    container = Container()
    await container.database.init()

    service = container.validation_service()
    pending_list = service.list_pending()

    # Filtrer les non-auto-valides (status PENDING)
    pending_list = [
        p for p in pending_list
        if p.validation_status == ValidationStatus.PENDING and not p.auto_validated
    ]

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente de validation manuelle.[/yellow]")
        return

    console.print(f"[bold]{len(pending_list)}[/bold] fichier(s) a valider.\n")

    validated = []
    for pending in pending_list:
        result = await validation_loop(pending, service)

        if result == "quit":
            console.print("[yellow]Validation interrompue.[/yellow]")
            break
        elif result == "trash":
            service.reject_pending(pending)
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Corbeille:[/red] {filename}")
        elif result is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[yellow]Passe:[/yellow] {filename}")
        else:
            # result est l'ID du candidat selectionne
            # Trouver le candidat correspondant
            candidate = None
            for c in pending.candidates:
                c_id = c.id if hasattr(c, "id") else c.get("id", "")
                if c_id == result:
                    # Convertir dict en SearchResult si necessaire
                    if isinstance(c, dict):
                        from src.core.ports.api_clients import SearchResult
                        candidate = SearchResult(
                            id=c.get("id", ""),
                            title=c.get("title", ""),
                            year=c.get("year"),
                            score=c.get("score", 0.0),
                            source=c.get("source", ""),
                        )
                    else:
                        candidate = c
                    break

            if candidate:
                details = await service.validate_candidate(pending, candidate)
                validated.append({"pending": pending, "details": details})
                filename = pending.video_file.filename if pending.video_file else "?"
                console.print(f"[green]Valide:[/green] {filename} -> {details.title}")

    console.print(f"\n[bold]{len(validated)}[/bold] fichier(s) valide(s).")


@validate_app.command("batch")
def validate_batch() -> None:
    """Affiche et execute le batch de transferts pour les fichiers valides."""
    asyncio.run(_validate_batch_async())


async def _validate_batch_async() -> None:
    """Implementation async du batch de transferts."""
    container = Container()
    config = container.config()
    await container.database.init()

    # Recuperer les services necessaires
    service = container.validation_service()
    renamer = container.renamer_service()
    organizer = container.organizer_service()

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

    # Construire la liste des transferts
    transfers = []
    storage_dir = Path(config.storage_dir)

    for pending in validated_list:
        # Recuperer le candidat selectionne
        candidate = None
        for c in pending.candidates:
            c_id = c.id if hasattr(c, "id") else c.get("id", "")
            if c_id == pending.selected_candidate_id:
                candidate = c
                break

        if candidate is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Erreur:[/red] Candidat non trouve pour {filename}")
            continue

        # Extraire les infos du candidat (dict ou SearchResult)
        if isinstance(candidate, dict):
            candidate_title = candidate.get("title", "")
            candidate_year = candidate.get("year")
            candidate_source = candidate.get("source", "")
        else:
            candidate_title = candidate.title
            candidate_year = candidate.year
            candidate_source = candidate.source

        # Determiner si c'est une serie
        is_series = candidate_source == "tvdb"

        # Extraire l'extension du fichier source
        source_path = pending.video_file.path if pending.video_file else None
        if source_path is None:
            filename = pending.video_file.filename if pending.video_file else "?"
            console.print(f"[red]Erreur:[/red] Chemin source manquant pour {filename}")
            continue

        extension = source_path.suffix if source_path.suffix else ".mkv"
        media_info = pending.video_file.media_info if pending.video_file else None

        # Generer le nouveau nom et chemin de destination
        if is_series:
            # Pour les series: extraire saison/episode du nom de fichier
            filename = pending.video_file.filename if pending.video_file else ""
            season_num, episode_num = _extract_series_info(filename)
            episode_title = ""  # Non disponible sans parsing complet

            # Construire les entites Series et Episode pour renamer/organizer
            series = Series(
                title=candidate_title,
                year=candidate_year,
            )
            episode = Episode(
                season_number=season_num,
                episode_number=episode_num,
                title=episode_title,
            )

            new_filename = renamer.generate_series_filename(
                series=series,
                episode=episode,
                media_info=media_info,
                extension=extension,
            )
            dest_dir = organizer.get_series_destination(
                series=series,
                season_number=season_num,
                storage_dir=storage_dir,
            )
        else:
            # Pour les films: construire entite Movie
            movie = Movie(
                title=candidate_title,
                year=candidate_year,
                genres=(),  # Genres seront enrichis si MediaDetails disponibles
            )

            new_filename = renamer.generate_movie_filename(
                movie=movie,
                media_info=media_info,
                extension=extension,
            )
            dest_dir = organizer.get_movie_destination(
                movie=movie,
                storage_dir=storage_dir,
            )

        transfers.append({
            "pending": pending,
            "source": source_path,
            "destination": dest_dir / new_filename,
            "new_filename": new_filename,
            "action": "move+symlink",
        })

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


async def _process_async(filter_type: MediaFilter, dry_run: bool) -> None:
    """Implementation async du workflow complet."""
    container = Container()
    config = container.config()
    await container.database.init()

    scanner = container.scanner_service()
    validation_svc = container.validation_service()

    # 1. Scan avec Progress
    console.print("\n[bold cyan]Etape 1/4: Scan des telechargements[/bold cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        scan_task = progress.add_task("[cyan]Scan en cours...", total=None)
        scan_results = []

        for result in scanner.scan_downloads():
            # Filtrer selon filter_type
            if (
                filter_type == MediaFilter.MOVIES
                and result.detected_type != MediaType.MOVIE
            ):
                continue
            if (
                filter_type == MediaFilter.SERIES
                and result.detected_type != MediaType.SERIES
            ):
                continue

            scan_results.append(result)
            progress.update(
                scan_task, description=f"[cyan]{result.video_file.filename}"
            )

        progress.update(
            scan_task, total=len(scan_results), completed=len(scan_results)
        )

    console.print(f"[bold]{len(scan_results)}[/bold] fichier(s) trouve(s)")

    if not scan_results:
        console.print("[yellow]Aucun fichier a traiter.[/yellow]")
        return

    # 2. Matching et creation des PendingValidation
    console.print("\n[bold cyan]Etape 2/4: Matching avec les APIs[/bold cyan]\n")

    # Note: Le matching complet necessite l'orchestration avec les clients API
    # Pour cette phase, on utilise le scanner qui fournit deja les infos parsees
    # Le matching sera fait via le service de validation existant
    pending_repo = container.pending_validation_repository()
    video_file_repo = container.video_file_repository()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        match_task = progress.add_task("[green]Matching...", total=len(scan_results))

        for result in scan_results:
            progress.update(
                match_task, description=f"[green]{result.video_file.filename}"
            )

            # Sauvegarder le VideoFile et creer un PendingValidation
            from src.core.entities.video import PendingValidation, VideoFile

            # Creer le VideoFile avec les infos extraites
            video_file = VideoFile(
                path=result.video_file.path,
                filename=result.video_file.filename,
                media_info=result.media_info,
            )
            saved_vf = video_file_repo.save(video_file)

            # Creer le PendingValidation (sans candidats pour l'instant)
            # Les candidats seront ajoutes par le matching API
            pending = PendingValidation(
                video_file=saved_vf,
                candidates=[],
            )
            pending_repo.save(pending)

            progress.advance(match_task)

    console.print(
        f"[bold]{len(scan_results)}[/bold] fichier(s) en attente de validation"
    )

    # 3. Auto-validation
    console.print("\n[bold cyan]Etape 3/4: Auto-validation[/bold cyan]\n")

    pending_list = validation_svc.list_pending()
    auto_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        auto_task = progress.add_task(
            "[magenta]Auto-validation...", total=len(pending_list)
        )

        for pend in pending_list:
            result = await validation_svc.process_auto_validation(pend)
            if result.auto_validated:
                auto_count += 1
            progress.advance(auto_task)

    console.print(f"[bold]{auto_count}[/bold] fichier(s) auto-valide(s)")

    # 4. Validation manuelle interactive (si pas dry_run)
    remaining = [
        p
        for p in validation_svc.list_pending()
        if p.validation_status == ValidationStatus.PENDING and not p.auto_validated
    ]

    if remaining and not dry_run:
        console.print(
            f"\n[bold cyan]Etape 4/4: Validation manuelle[/bold cyan]"
            f" ({len(remaining)} fichier(s))\n"
        )

        validated_manual = 0
        for pend in remaining:
            result = await validation_loop(pend, validation_svc)

            if result == "quit":
                console.print("[yellow]Validation interrompue.[/yellow]")
                break
            elif result == "trash":
                validation_svc.reject_pending(pend)
                filename = pend.video_file.filename if pend.video_file else "?"
                console.print(f"[red]Corbeille:[/red] {filename}")
            elif result is None:
                filename = pend.video_file.filename if pend.video_file else "?"
                console.print(f"[yellow]Passe:[/yellow] {filename}")
            else:
                # Valide avec le candidat selectionne
                candidate = None
                for c in pend.candidates:
                    c_id = c.id if hasattr(c, "id") else c.get("id", "")
                    if c_id == result:
                        if isinstance(c, dict):
                            from src.core.ports.api_clients import SearchResult

                            candidate = SearchResult(
                                id=c.get("id", ""),
                                title=c.get("title", ""),
                                year=c.get("year"),
                                score=c.get("score", 0.0),
                                source=c.get("source", ""),
                            )
                        else:
                            candidate = c
                        break

                if candidate:
                    await validation_svc.validate_candidate(pend, candidate)
                    validated_manual += 1
                    filename = pend.video_file.filename if pend.video_file else "?"
                    console.print(f"[green]Valide:[/green] {filename}")

        console.print(f"\n[bold]{validated_manual}[/bold] fichier(s) valide(s) manuellement")

    # 5. Batch transfer (si pas dry_run)
    validated_list = validation_svc.list_validated()

    if dry_run:
        console.print("\n[yellow]Mode dry-run - aucun transfert effectue[/yellow]")
        console.print(
            f"[dim]{len(validated_list)} fichier(s) seraient transferes[/dim]"
        )
    elif validated_list:
        console.print(f"\n[bold cyan]Transfert des fichiers valides[/bold cyan]\n")

        # Reutiliser la logique de _validate_batch_async
        renamer = container.renamer_service()
        organizer = container.organizer_service()
        transferer = container.transferer_service(
            storage_dir=Path(config.storage_dir),
            video_dir=Path(config.video_dir),
        )
        storage_dir = Path(config.storage_dir)

        transfers = []
        for pend in validated_list:
            candidate = None
            for c in pend.candidates:
                c_id = c.id if hasattr(c, "id") else c.get("id", "")
                if c_id == pend.selected_candidate_id:
                    candidate = c
                    break

            if candidate is None:
                continue

            if isinstance(candidate, dict):
                candidate_title = candidate.get("title", "")
                candidate_year = candidate.get("year")
                candidate_source = candidate.get("source", "")
            else:
                candidate_title = candidate.title
                candidate_year = candidate.year
                candidate_source = candidate.source

            is_series = candidate_source == "tvdb"
            source_path = pend.video_file.path if pend.video_file else None
            if source_path is None:
                continue

            extension = source_path.suffix if source_path.suffix else ".mkv"
            media_info = pend.video_file.media_info if pend.video_file else None

            if is_series:
                filename = pend.video_file.filename if pend.video_file else ""
                season_num, episode_num = _extract_series_info(filename)
                series = Series(title=candidate_title, year=candidate_year)
                episode = Episode(
                    season_number=season_num,
                    episode_number=episode_num,
                    title="",
                )
                new_filename = renamer.generate_series_filename(
                    series=series,
                    episode=episode,
                    media_info=media_info,
                    extension=extension,
                )
                dest_dir = organizer.get_series_destination(
                    series=series,
                    season_number=season_num,
                    storage_dir=storage_dir,
                )
            else:
                movie = Movie(
                    title=candidate_title,
                    year=candidate_year,
                    genres=(),
                )
                new_filename = renamer.generate_movie_filename(
                    movie=movie,
                    media_info=media_info,
                    extension=extension,
                )
                dest_dir = organizer.get_movie_destination(
                    movie=movie,
                    storage_dir=storage_dir,
                )

            transfers.append({
                "pending": pend,
                "source": source_path,
                "destination": dest_dir / new_filename,
                "new_filename": new_filename,
                "action": "move+symlink",
            })

        if transfers:
            display_batch_summary(transfers)
            if Confirm.ask("\n[bold]Executer le transfert ?[/bold]", default=False):
                results = await execute_batch_transfer(transfers, transferer)
                success_count = sum(1 for r in results if r.get("success", False))
                console.print(
                    f"\n[bold green]{success_count}[/bold green] fichier(s) transfere(s)"
                )

    # 6. Resume final
    console.print("\n[bold]Resume:[/bold]")
    console.print(f"  Scannes: {len(scan_results)}")
    console.print(f"  Auto-valides: {auto_count}")
    if validated_list:
        console.print(f"  Total valides: {len(validated_list)}")


def pending(
    all_files: Annotated[
        bool,
        typer.Option("--all", "-a", help="Afficher tous les fichiers sans pagination"),
    ] = False,
) -> None:
    """Affiche les fichiers en attente de validation."""
    asyncio.run(_pending_async(all_files))


async def _pending_async(all_files: bool) -> None:
    """Implementation async de la commande pending."""
    container = Container()
    await container.database.init()

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


async def _validate_file_async(file_id: str) -> None:
    """Implementation async de validate file."""
    container = Container()
    await container.database.init()

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
        # Valide avec le candidat selectionne
        candidate = None
        for c in pend.candidates:
            c_id = c.id if hasattr(c, "id") else c.get("id", "")
            if c_id == result:
                if isinstance(c, dict):
                    from src.core.ports.api_clients import SearchResult

                    candidate = SearchResult(
                        id=c.get("id", ""),
                        title=c.get("title", ""),
                        year=c.get("year"),
                        score=c.get("score", 0.0),
                        source=c.get("source", ""),
                    )
                else:
                    candidate = c
                break

        if candidate:
            details = await validation_svc.validate_candidate(pend, candidate)
            console.print(f"[green]Fichier valide: {details.title}[/green]")
