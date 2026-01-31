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


def _display_transfer_tree(transfers: list[dict], storage_dir: Path) -> None:
    """
    Affiche l'arborescence des transferts prevus en mode dry-run.

    Organise les transferts par type (Films/Series) puis par repertoire
    pour une visualisation claire de la structure de destination.

    Args:
        transfers: Liste des transferts avec source, destination, etc.
        storage_dir: Repertoire de stockage racine
    """
    # Separer films et series
    movies = [t for t in transfers if not t.get("is_series", False)]
    series = [t for t in transfers if t.get("is_series", False)]

    # Arbre principal
    tree = Tree(f"[bold blue]{storage_dir}[/bold blue]")

    # Branche Films
    if movies:
        films_branch = tree.add("[bold cyan]Films/[/bold cyan]")
        # Grouper par sous-repertoire relatif
        movie_dirs: dict[str, list[dict]] = {}
        for m in movies:
            dest = m["destination"]
            # Chemin relatif depuis storage_dir
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

    # Branche Series
    if series:
        series_branch = tree.add("[bold magenta]Séries/[/bold magenta]")
        # Grouper par serie puis par saison
        series_groups: dict[str, dict[str, list[dict]]] = {}
        for s in series:
            title = s.get("title", "Inconnu")
            year = s.get("year", "")
            series_key = f"{title} ({year})" if year else title

            dest = s["destination"]
            # Extraire le nom de la saison
            season_dir = dest.parent.name  # ex: "Saison 01"

            if series_key not in series_groups:
                series_groups[series_key] = {}
            if season_dir not in series_groups[series_key]:
                series_groups[series_key][season_dir] = []
            series_groups[series_key][season_dir].append(s)

        for series_name in sorted(series_groups.keys()):
            series_sub = series_branch.add(f"[magenta]{series_name}/[/magenta]")
            for season in sorted(series_groups[series_name].keys()):
                season_sub = series_sub.add(f"[dim]{season}/[/dim]")
                episodes = series_groups[series_name][season]
                # Trier par numero d'episode
                episodes.sort(key=lambda e: e["new_filename"])
                for ep in episodes:
                    new_name = ep["new_filename"]
                    season_sub.add(f"[green]{new_name}[/green]")

    console.print(tree)

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
    container.database.init()

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
    container.database.init()

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
    container.database.init()

    # Recuperer les services necessaires
    service = container.validation_service()
    renamer = container.renamer_service()
    organizer = container.organizer_service()
    tvdb_client = container.tvdb_client()

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

            # Recuperer le titre d'episode depuis TVDB
            episode_title = ""
            if isinstance(candidate, dict):
                series_id = candidate.get("id", "")
            else:
                series_id = candidate.id

            if tvdb_client and getattr(tvdb_client, "_api_key", None) and series_id:
                try:
                    ep_details = await tvdb_client.get_episode_details(
                        series_id, season_num, episode_num
                    )
                    if ep_details and ep_details.title:
                        episode_title = ep_details.title
                except Exception:
                    pass  # Garder episode_title vide en cas d'erreur

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
    container.database.init()

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

    pending_repo = container.pending_validation_repository()
    video_file_repo = container.video_file_repository()
    tmdb_client = container.tmdb_client()
    tvdb_client = container.tvdb_client()
    matcher = container.matcher_service()

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

            # Rechercher les candidats via API
            candidates = []
            title = result.parsed_info.title
            year = result.parsed_info.year

            if result.detected_type == MediaType.MOVIE:
                # Film -> TMDB
                if tmdb_client and getattr(tmdb_client, "_api_key", None):
                    try:
                        api_results = await tmdb_client.search(title, year=year)
                        duration = None
                        if result.media_info and result.media_info.duration_seconds:
                            duration = result.media_info.duration_seconds

                        # Premier scoring sans duree API (utilise coefficients fallback)
                        candidates = matcher.score_results(
                            api_results, title, year, duration
                        )

                        # Enrichir les top 3 candidats avec leurs details (duree)
                        # puis re-scorer avec les coefficients complets
                        if candidates and duration:
                            top_candidates = candidates[:3]
                            enriched_candidates = []

                            for cand in top_candidates:
                                try:
                                    details = await tmdb_client.get_details(cand.id)
                                    if details and details.duration_seconds:
                                        # Re-scorer avec la duree API et titre original
                                        from src.services.matcher import calculate_movie_score
                                        new_score = calculate_movie_score(
                                            query_title=title,
                                            query_year=year,
                                            query_duration=duration,
                                            candidate_title=cand.title,
                                            candidate_year=cand.year,
                                            candidate_duration=details.duration_seconds,
                                            candidate_original_title=cand.original_title or details.original_title,
                                        )
                                        from dataclasses import replace
                                        cand = replace(cand, score=new_score)
                                except Exception:
                                    pass  # Garder le score fallback
                                enriched_candidates.append(cand)

                            # Remplacer les top candidats et re-trier
                            candidates = enriched_candidates + candidates[3:]
                            candidates.sort(key=lambda c: c.score, reverse=True)

                    except Exception as e:
                        console.print(f"[yellow]Erreur TMDB pour {title}: {e}[/yellow]")
            else:
                # Serie -> TVDB
                if tvdb_client and getattr(tvdb_client, "_api_key", None):
                    try:
                        api_results = await tvdb_client.search(title, year=year)
                        # Scorer les resultats (series: 100% titre)
                        candidates = matcher.score_results(
                            api_results, title, year, None, is_series=True
                        )
                    except Exception as e:
                        console.print(f"[yellow]Erreur TVDB pour {title}: {e}[/yellow]")

            # Convertir les candidats en format dict pour stockage
            candidates_data = [
                {
                    "id": c.id,
                    "title": c.title,
                    "year": c.year,
                    "score": c.score,
                    "source": c.source,
                }
                for c in candidates
            ]

            # Creer le PendingValidation avec les candidats
            pending = PendingValidation(
                video_file=saved_vf,
                candidates=candidates_data,
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

    # 5. Batch transfer (ou affichage dry-run)
    validated_list = validation_svc.list_validated()

    # Construire la liste des transferts (pour dry-run et execution)
    renamer = container.renamer_service()
    organizer = container.organizer_service()
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

            # Recuperer le titre d'episode depuis TVDB
            episode_title = ""
            if isinstance(candidate, dict):
                series_id = candidate.get("id", "")
            else:
                series_id = candidate.id

            if tvdb_client and getattr(tvdb_client, "_api_key", None) and series_id:
                try:
                    ep_details = await tvdb_client.get_episode_details(
                        series_id, season_num, episode_num
                    )
                    if ep_details and ep_details.title:
                        episode_title = ep_details.title
                except Exception:
                    pass  # Garder episode_title vide en cas d'erreur

            series = Series(title=candidate_title, year=candidate_year)
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
            "is_series": is_series,
            "title": candidate_title,
            "year": candidate_year,
        })

    if dry_run:
        console.print("\n[yellow]Mode dry-run - aucun transfert effectue[/yellow]")
        console.print(f"[dim]{len(transfers)} fichier(s) seraient transferes[/dim]\n")

        # Afficher l'arborescence des transferts
        if transfers:
            _display_transfer_tree(transfers, storage_dir)
    elif transfers:
        console.print(f"\n[bold cyan]Transfert des fichiers valides[/bold cyan]\n")
        transferer = container.transferer_service(
            storage_dir=Path(config.storage_dir),
            video_dir=Path(config.video_dir),
        )
        # Ajouter action pour le transferer
        for t in transfers:
            t["action"] = "move+symlink"

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
    container.database.init()

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
    container.database.init()

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


# ============================================================================
# Commande import
# ============================================================================


def import_library(
    storage_dir: Annotated[
        Optional[Path],
        typer.Argument(help="Repertoire de la videotheque a importer"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la BDD"),
    ] = False,
) -> None:
    """Importe une videotheque existante dans la base de donnees."""
    asyncio.run(_import_library_async(storage_dir, dry_run))


async def _import_library_async(storage_dir: Optional[Path], dry_run: bool) -> None:
    """Implementation async de la commande import."""
    from src.services.importer import ImportDecision

    container = Container()
    config = container.config()
    container.database.init()

    # Utiliser storage_dir depuis config si non fourni
    if storage_dir is None:
        storage_dir = Path(config.storage_dir)

    # Verifier que le repertoire existe
    if not storage_dir.exists():
        console.print(f"[red]Erreur:[/red] Repertoire introuvable: {storage_dir}")
        raise typer.Exit(code=1)

    if dry_run:
        console.print("[yellow]Mode dry-run - aucune modification[/yellow]\n")

    # Creer le service d'import
    importer = container.importer_service(dry_run=dry_run)

    # Compteurs
    imported = 0
    skipped = 0
    errors = 0

    console.print(f"[bold cyan]Import de la videotheque[/bold cyan]: {storage_dir}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        import_task = progress.add_task("[cyan]Scan en cours...", total=None)

        for result in importer.scan_library(storage_dir):
            # Mettre a jour la description avec le nom du fichier
            progress.update(import_task, description=f"[cyan]{result.filename}")

            # Mettre a jour les compteurs
            if result.decision == ImportDecision.IMPORT:
                imported += 1
            elif result.decision == ImportDecision.SKIP_KNOWN:
                skipped += 1
            elif result.decision == ImportDecision.UPDATE_PATH:
                skipped += 1  # Compte comme skip (fichier deja connu)
            elif result.decision == ImportDecision.ERROR:
                errors += 1
                console.print(
                    f"[red]Erreur:[/red] {result.filename}: {result.error_message}"
                )

        # Marquer comme termine
        progress.update(
            import_task,
            total=imported + skipped + errors,
            completed=imported + skipped + errors,
            description="[green]Termine",
        )

    # Afficher le resume final
    console.print("\n[bold]Resume de l'import:[/bold]")
    console.print(f"  [green]{imported}[/green] importe(s)")
    console.print(f"  [yellow]{skipped}[/yellow] ignore(s)")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")


# ============================================================================
# Commande enrich
# ============================================================================


def enrich() -> None:
    """Enrichit les metadonnees des fichiers via API."""
    asyncio.run(_enrich_async())


async def _enrich_async() -> None:
    """Implementation async de la commande enrich."""
    container = Container()
    container.database.init()

    enricher = container.enricher_service()

    # Recuperer les fichiers a enrichir
    pending = enricher.list_pending_enrichment()

    if not pending:
        console.print("[yellow]Aucun fichier a enrichir.[/yellow]")
        console.print("[dim]Tous les fichiers ont deja des candidats.[/dim]")
        return

    console.print(f"[bold cyan]Enrichissement API[/bold cyan]: {len(pending)} fichier(s)\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        enrich_task = progress.add_task("[cyan]Enrichissement...", total=len(pending))

        def update_description(filename: str) -> None:
            progress.update(enrich_task, description=f"[cyan]{filename}")

        def advance() -> None:
            progress.advance(enrich_task)

        result = await enricher.enrich_batch(
            items=pending,
            progress_callback=update_description,
            advance_callback=advance,
        )

    # Afficher le resume
    console.print("\n[bold]Resume de l'enrichissement:[/bold]")
    console.print(f"  [green]{result.enriched}[/green] enrichi(s)")
    console.print(f"  [red]{result.failed}[/red] echec(s)")
    if result.skipped > 0:
        console.print(f"  [yellow]{result.skipped}[/yellow] ignore(s)")


# ============================================================================
# Commande repair-links
# ============================================================================


def repair_links() -> None:
    """Detecte et repare les symlinks casses interactivement."""
    asyncio.run(_repair_links_async())


async def _repair_links_async() -> None:
    """Implementation async de la commande repair-links."""
    from rich.prompt import Prompt

    from src.services.integrity import RepairAction, RepairActionType

    container = Container()
    config = container.config()
    container.database.init()

    # Creer le service de reparation avec les paths
    repair = container.repair_service(
        storage_dir=Path(config.storage_dir),
        video_dir=Path(config.video_dir),
        trash_dir=Path(config.storage_dir).parent / "trash",  # Dossier trash adjacent
    )

    # Trouver les symlinks casses
    broken = repair.find_broken_symlinks()

    if not broken:
        console.print("[green]Aucun symlink casse detecte.[/green]")
        return

    console.print(f"[bold cyan]Symlinks casses[/bold cyan]: {len(broken)} detecte(s)\n")

    actions: list[RepairAction] = []

    for link in broken:
        # Afficher les infos du lien
        try:
            original_target = link.readlink()
        except OSError:
            original_target = Path("<inconnu>")

        panel_content = [
            f"[bold]{link.name}[/bold]",
            f"Chemin: {link}",
            f"Cible originale: [red]{original_target}[/red]",
        ]
        console.print(Panel("\n".join(panel_content), title="Symlink casse"))

        # Chercher des cibles possibles
        targets = repair.find_possible_targets(link)

        if targets:
            console.print(f"\n[green]{len(targets)}[/green] cible(s) possible(s):")
            for i, target in enumerate(targets[:5], 1):
                console.print(f"  {i}. {target}")
            if len(targets) > 5:
                console.print(f"  [dim]... et {len(targets) - 5} autre(s)[/dim]")

        # Prompt interactif
        choices = ["chercher", "supprimer", "ignorer", "quitter"]
        choice = Prompt.ask(
            "\nAction",
            choices=choices,
            default="ignorer",
        )

        if choice == "quitter":
            console.print("[yellow]Reparation interrompue.[/yellow]")
            break

        elif choice == "ignorer":
            actions.append(
                RepairAction(link=link, action=RepairActionType.SKIPPED)
            )
            console.print("[dim]Ignore[/dim]\n")

        elif choice == "supprimer":
            dest = repair.move_to_orphans(link)
            if dest:
                actions.append(
                    RepairAction(link=link, action=RepairActionType.ORPHANED)
                )
                console.print(f"[yellow]Deplace vers orphans[/yellow]\n")
            else:
                console.print("[red]Echec du deplacement[/red]\n")

        elif choice == "chercher":
            if not targets:
                console.print("[red]Aucune cible trouvee[/red]\n")
                actions.append(
                    RepairAction(link=link, action=RepairActionType.SKIPPED)
                )
                continue

            # Selection de la cible
            target_choices = [str(i) for i in range(1, min(6, len(targets) + 1))]
            target_choice = Prompt.ask(
                "Selectionner la cible",
                choices=target_choices + ["annuler"],
                default="1",
            )

            if target_choice == "annuler":
                actions.append(
                    RepairAction(link=link, action=RepairActionType.SKIPPED)
                )
                console.print("[dim]Annule[/dim]\n")
            else:
                target_idx = int(target_choice) - 1
                new_target = targets[target_idx]
                success = repair.repair_symlink(link, new_target)

                if success:
                    actions.append(
                        RepairAction(
                            link=link,
                            action=RepairActionType.REPAIRED,
                            new_target=new_target,
                        )
                    )
                    console.print(f"[green]Repare -> {new_target}[/green]\n")
                else:
                    console.print("[red]Echec de la reparation[/red]\n")

    # Sauvegarder le log
    if actions:
        log_path = repair.save_log(actions)
        if log_path:
            console.print(f"\n[dim]Log sauvegarde: {log_path}[/dim]")

    # Resume
    repaired = sum(1 for a in actions if a.action == RepairActionType.REPAIRED)
    orphaned = sum(1 for a in actions if a.action == RepairActionType.ORPHANED)
    skipped = sum(1 for a in actions if a.action == RepairActionType.SKIPPED)

    console.print("\n[bold]Resume:[/bold]")
    console.print(f"  [green]{repaired}[/green] repare(s)")
    console.print(f"  [yellow]{orphaned}[/yellow] deplace(s) vers orphans")
    console.print(f"  [dim]{skipped} ignore(s)[/dim]")


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
