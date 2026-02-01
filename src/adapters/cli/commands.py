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
from src.services.transferer import ExistingFileInfo, SimilarContentInfo
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
    tmdb_client = container.tmdb_client()

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
        video_dir = Path(config.video_dir)

        # Extraire la langue du nom de fichier (fallback si mediainfo n'a pas de langue)
        original_filename = pending.video_file.filename if pending.video_file else ""
        fallback_language = _extract_language_from_filename(original_filename)

        # Generer le nouveau nom et chemin de destination
        if is_series:
            # Pour les series: extraire saison/episode du nom de fichier
            filename = pending.video_file.filename if pending.video_file else ""
            season_num, episode_num = _extract_series_info(filename)

            # Recuperer le titre d'episode et les genres depuis TVDB
            episode_title = ""
            series_genres: tuple[str, ...] = ()
            if isinstance(candidate, dict):
                series_id = candidate.get("id", "")
            else:
                series_id = candidate.id

            if tvdb_client and getattr(tvdb_client, "_api_key", None) and series_id:
                try:
                    # Recuperer les details de la serie (genres)
                    series_details = await tvdb_client.get_details(series_id)
                    if series_details and series_details.genres:
                        series_genres = series_details.genres

                    # Recuperer le titre d'episode
                    ep_details = await tvdb_client.get_episode_details(
                        series_id, season_num, episode_num
                    )
                    if ep_details and ep_details.title:
                        episode_title = ep_details.title
                except Exception:
                    pass  # Garder les valeurs par defaut en cas d'erreur

            # Construire les entites Series et Episode pour renamer/organizer
            series = Series(
                title=candidate_title,
                year=candidate_year,
                genres=series_genres,
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
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_series_destination(
                series=series,
                season_number=season_num,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            # Chemin personnalise pour le symlink (avec type de serie)
            symlink_dir = organizer.get_series_video_destination(
                series=series,
                season_number=season_num,
                video_dir=video_dir,
            )
        else:
            # Pour les films: recuperer les genres depuis TMDB
            movie_genres: tuple[str, ...] = ()
            if isinstance(candidate, dict):
                movie_id = candidate.get("id", "")
            else:
                movie_id = candidate.id

            if tmdb_client and getattr(tmdb_client, "_api_key", None) and movie_id:
                try:
                    movie_details = await tmdb_client.get_details(movie_id)
                    if movie_details and movie_details.genres:
                        movie_genres = movie_details.genres
                except Exception:
                    pass  # Garder genres vide en cas d'erreur

            movie = Movie(
                title=candidate_title,
                year=candidate_year,
                genres=movie_genres,
            )

            new_filename = renamer.generate_movie_filename(
                movie=movie,
                media_info=media_info,
                extension=extension,
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_movie_destination(
                movie=movie,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            # Chemin personnalise pour le symlink (avec genre et subdivisions)
            video_dir = Path(config.video_dir)
            symlink_dir = organizer.get_movie_video_destination(
                movie=movie,
                video_dir=video_dir,
            )

        transfer_data = {
            "pending": pending,
            "source": source_path,
            "destination": dest_dir / new_filename,
            "new_filename": new_filename,
            "action": "move+symlink",
        }
        # Ajouter le chemin de symlink personnalise pour les series
        if symlink_dir:
            transfer_data["symlink_destination"] = symlink_dir / new_filename
        transfers.append(transfer_data)

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

    # Nettoyage des enregistrements orphelins (runs precedents interrompus)
    pending_repo = container.pending_validation_repository()
    video_file_repo = container.video_file_repository()
    orphan_count = 0
    # Recuperer les pending et validated (tout sauf TRANSFERRED)
    orphans = validation_svc.list_pending() + validation_svc.list_validated()
    for pv in orphans:
        if pv.id:
            pending_repo.delete(pv.id)
        if pv.video_file and pv.video_file.id:
            video_file_repo.delete(pv.video_file.id)
        orphan_count += 1
    if orphan_count > 0:
        console.print(
            f"[dim]Nettoyage: {orphan_count} enregistrement(s) orphelin(s) supprime(s)[/dim]\n"
        )

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

    # Liste pour collecter les IDs crees pendant le scan (pour nettoyage dry-run)
    created_video_file_ids: list[str] = []

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

            # Collecter l'ID pour nettoyage en cas de dry-run
            if saved_vf.id:
                created_video_file_ids.append(saved_vf.id)

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
    video_dir = Path(config.video_dir)
    # Deux repertoires staging separes
    # Video: au niveau parent (ex: /media/Serveur/test -> /media/Serveur/staging)
    # Storage: a la racine du stockage (ex: /media/NAS64 -> /media/NAS64/staging)
    video_staging_dir = video_dir.parent / "staging"
    storage_staging_dir = storage_dir / "staging"

    # Creer le transferer pour la detection de conflits
    transferer = container.transferer_service(
        storage_dir=storage_dir,
        video_dir=video_dir,
    )

    transfers = []
    # Cache des decisions de conflit par serie/saison (cle: "titre|annee|saison")
    conflict_decisions: dict[str, str] = {}
    # Cache des infos de conflit similaire deja detectes
    similar_cache: dict[str, "SimilarContentInfo | None"] = {}

    for pend in validated_list:
        # Ne traiter que les fichiers de cette session (pas les anciens de la DB)
        if not pend.video_file or not pend.video_file.id:
            continue
        if pend.video_file.id not in created_video_file_ids:
            continue

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

        # Extraire la langue du nom de fichier (fallback si mediainfo n'a pas de langue)
        original_filename = pend.video_file.filename if pend.video_file else ""
        fallback_language = _extract_language_from_filename(original_filename)

        if is_series:
            filename = pend.video_file.filename if pend.video_file else ""
            season_num, episode_num = _extract_series_info(filename)

            # Recuperer le titre d'episode et les genres depuis TVDB
            episode_title = ""
            series_genres: tuple[str, ...] = ()
            if isinstance(candidate, dict):
                series_id = candidate.get("id", "")
            else:
                series_id = candidate.id

            if tvdb_client and getattr(tvdb_client, "_api_key", None) and series_id:
                try:
                    # Recuperer les details de la serie (genres)
                    series_details = await tvdb_client.get_details(series_id)
                    if series_details and series_details.genres:
                        series_genres = series_details.genres

                    # Recuperer le titre d'episode
                    ep_details = await tvdb_client.get_episode_details(
                        series_id, season_num, episode_num
                    )
                    if ep_details and ep_details.title:
                        episode_title = ep_details.title
                except Exception:
                    pass  # Garder les valeurs par defaut en cas d'erreur

            series = Series(
                title=candidate_title,
                year=candidate_year,
                genres=series_genres,
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
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_series_destination(
                series=series,
                season_number=season_num,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            # Chemin personnalise pour le symlink (avec type de serie)
            symlink_dir = organizer.get_series_video_destination(
                series=series,
                season_number=season_num,
                video_dir=video_dir,
            )
        else:
            # Pour les films: recuperer les genres depuis TMDB
            movie_genres: tuple[str, ...] = ()
            if isinstance(candidate, dict):
                movie_id = candidate.get("id", "")
            else:
                movie_id = candidate.id

            if tmdb_client and getattr(tmdb_client, "_api_key", None) and movie_id:
                try:
                    movie_details = await tmdb_client.get_details(movie_id)
                    if movie_details and movie_details.genres:
                        movie_genres = movie_details.genres
                except Exception:
                    pass  # Garder genres vides en cas d'erreur

            movie = Movie(
                title=candidate_title,
                year=candidate_year,
                genres=movie_genres,
            )
            new_filename = renamer.generate_movie_filename(
                movie=movie,
                media_info=media_info,
                extension=extension,
                fallback_language=fallback_language,
            )
            dest_dir = organizer.get_movie_destination(
                movie=movie,
                storage_dir=storage_dir,
                video_dir=video_dir,
            )
            # Chemin personnalise pour le symlink (avec genre et subdivisions)
            symlink_dir = organizer.get_movie_video_destination(
                movie=movie,
                video_dir=video_dir,
            )

        # Detection de contenu similaire
        skip_transfer = False

        # Cle de cache: serie+saison ou film
        if is_series:
            cache_key = f"{candidate_title}|{candidate_year}|{season_num}"
        else:
            cache_key = f"{candidate_title}|{candidate_year}"

        # Verifier si on a deja une decision pour ce groupe
        if cache_key in conflict_decisions:
            # Appliquer la decision deja prise
            cached_resolution = conflict_decisions[cache_key]
            if cached_resolution in (ConflictResolution.SKIP, ConflictResolution.KEEP_OLD):
                skip_transfer = True
            # KEEP_NEW et KEEP_BOTH: on continue le transfert
        else:
            # Premiere rencontre de ce groupe: detecter les conflits
            if is_series:
                search_dir = symlink_dir.parent.parent  # Lettre/Serie/Saison -> Lettre
            else:
                search_dir = symlink_dir

            # Verifier le cache de detection (eviter de rescanner le meme repertoire)
            if cache_key not in similar_cache:
                similar_cache[cache_key] = transferer.find_similar_content(
                    title=candidate_title,
                    year=candidate_year,
                    destination_dir=search_dir,
                    is_series=is_series,
                )

            similar = similar_cache[cache_key]

            if similar:
                # Compter tous les fichiers du meme groupe dans validated_list
                new_files_count = 0
                new_files_total_size = 0
                new_files_resolutions: set[str] = set()
                new_files_video_codecs: set[str] = set()
                new_files_audio_codecs: set[str] = set()

                for other_pend in validated_list:
                    # Ne compter que les fichiers de cette session
                    if not other_pend.video_file or not other_pend.video_file.id:
                        continue
                    if other_pend.video_file.id not in created_video_file_ids:
                        continue

                    # Recuperer les infos du candidat
                    other_candidate = None
                    for c in other_pend.candidates:
                        c_id = c.id if hasattr(c, "id") else c.get("id", "")
                        if c_id == other_pend.selected_candidate_id:
                            other_candidate = c
                            break
                    if other_candidate is None:
                        continue

                    if isinstance(other_candidate, dict):
                        other_title = other_candidate.get("title", "")
                        other_year = other_candidate.get("year")
                        other_source = other_candidate.get("source", "")
                    else:
                        other_title = other_candidate.title
                        other_year = other_candidate.year
                        other_source = other_candidate.source

                    other_is_series = other_source == "tvdb"

                    # Construire la cle de l'autre fichier
                    if other_is_series:
                        other_filename = other_pend.video_file.filename if other_pend.video_file else ""
                        other_season, _ = _extract_series_info(other_filename)
                        other_key = f"{other_title}|{other_year}|{other_season}"
                    else:
                        other_key = f"{other_title}|{other_year}"

                    # Si meme groupe, agreger les infos
                    if other_key == cache_key:
                        new_files_count += 1
                        other_path = other_pend.video_file.path
                        if other_path and other_path.exists():
                            new_files_total_size += other_path.stat().st_size
                        other_media = other_pend.video_file.media_info
                        if other_media:
                            if other_media.resolution:
                                new_files_resolutions.add(other_media.resolution.label)
                            if other_media.video_codec:
                                new_files_video_codecs.add(other_media.video_codec.name)
                            if other_media.audio_codecs:
                                new_files_audio_codecs.add(other_media.audio_codecs[0].name)

                # Creer les infos agregees du nouveau contenu
                new_file_info = ExistingFileInfo(
                    path=source_path,
                    size_bytes=new_files_total_size,
                    resolution=", ".join(sorted(new_files_resolutions)) or None,
                    video_codec=", ".join(sorted(new_files_video_codecs)) or None,
                    audio_codec=", ".join(sorted(new_files_audio_codecs)) or None,
                    duration_seconds=None,
                )

                # Afficher le conflit et demander la resolution
                display_similar_content_conflict(similar, new_file_info, new_file_count=new_files_count)
                resolution = prompt_conflict_resolution()

                # Cacher la decision pour les autres fichiers du groupe
                conflict_decisions[cache_key] = resolution

                if resolution == ConflictResolution.SKIP:
                    console.print(f"[yellow]Groupe passe ({new_files_count} fichier(s))[/yellow]")
                    skip_transfer = True
                elif resolution == ConflictResolution.KEEP_OLD:
                    console.print(f"[yellow]Nouveau contenu ignore ({new_files_count} fichier(s))[/yellow]")
                    skip_transfer = True
                elif resolution == ConflictResolution.KEEP_NEW:
                    if dry_run:
                        console.print(f"[dim]Dry-run: l'ancien serait deplace vers staging[/dim]")
                    else:
                        console.print(f"[cyan]Deplacement de l'ancien vers staging...[/cyan]")
                        try:
                            # 1. Collecter les mappings symlink -> cible AVANT de deplacer
                            symlink_mappings: list[tuple[Path, Path]] = []
                            storage_source_dir = None
                            for item in similar.existing_dir.rglob("*"):
                                if item.is_symlink():
                                    target = item.resolve()
                                    symlink_mappings.append((item, target))
                                    if storage_source_dir is None:
                                        # Remonter au niveau du repertoire serie/film
                                        storage_source_dir = target.parent.parent

                            # 2. Deplacer le stockage vers storage_staging_dir
                            storage_staging_path = None
                            if storage_source_dir and storage_source_dir.exists():
                                storage_staging_path = transferer.move_to_staging(
                                    storage_source_dir, storage_staging_dir, preserve_structure=True
                                )

                            # 3. Deplacer les symlinks vers video_staging_dir
                            video_staging_path = transferer.move_to_staging(
                                similar.existing_dir, video_staging_dir, preserve_structure=True
                            )

                            # 4. Mettre a jour les symlinks pour pointer vers le nouveau stockage
                            if storage_staging_path and video_staging_path:
                                for old_symlink, old_target in symlink_mappings:
                                    # Calculer le nouveau chemin du symlink
                                    rel_to_existing = old_symlink.relative_to(similar.existing_dir)
                                    new_symlink = video_staging_path / rel_to_existing
                                    # Calculer le nouveau chemin de la cible
                                    rel_to_storage = old_target.relative_to(storage_source_dir)
                                    new_target = storage_staging_path / rel_to_storage
                                    # Recréer le symlink
                                    if new_symlink.exists() or new_symlink.is_symlink():
                                        new_symlink.unlink()
                                    new_symlink.symlink_to(new_target)

                            console.print(f"[green]Ancien contenu deplace vers staging[/green]")
                        except (ValueError, OSError) as e:
                            console.print(f"[yellow]Avertissement: erreur lors du deplacement: {e}[/yellow]")
                elif resolution == ConflictResolution.KEEP_BOTH:
                    console.print(f"[green]Les deux versions seront conservees[/green]")

        if skip_transfer:
            continue

        transfer_data = {
            "pending": pend,
            "source": source_path,
            "destination": dest_dir / new_filename,
            "new_filename": new_filename,
            "is_series": is_series,
            "title": candidate_title,
            "year": candidate_year,
        }
        # Ajouter le chemin de symlink personnalise
        if symlink_dir:
            transfer_data["symlink_destination"] = symlink_dir / new_filename
        transfers.append(transfer_data)

    if dry_run:
        console.print("\n[yellow]Mode dry-run - aucun transfert effectue[/yellow]")
        console.print(f"[dim]{len(transfers)} fichier(s) seraient transferes[/dim]\n")

        # Afficher l'arborescence des transferts (symlinks dans video_dir)
        if transfers:
            _display_transfer_tree(transfers, storage_dir, video_dir)
    elif transfers:
        console.print(f"\n[bold cyan]Transfert des fichiers valides[/bold cyan]\n")
        # Ajouter action pour le transferer (transferer deja cree plus haut)
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

    # 7. Nettoyage dry-run : supprimer les donnees creees pendant le scan
    if dry_run and created_video_file_ids:
        # Supprimer d'abord les PendingValidation (cle etrangere vers VideoFile)
        for vf_id in created_video_file_ids:
            pv = pending_repo.get_by_video_file_id(vf_id)
            if pv and pv.id:
                pending_repo.delete(pv.id)
        # Puis supprimer les VideoFile
        for vf_id in created_video_file_ids:
            video_file_repo.delete(vf_id)
        console.print(
            f"\n[dim]Dry-run: {len(created_video_file_ids)} enregistrement(s) "
            f"temporaire(s) nettoye(s)[/dim]"
        )


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


async def _import_library_async(
    source_dir: Optional[Path], dry_run: bool, from_symlinks: bool
) -> None:
    """Implementation async de la commande import."""
    from src.services.importer import ImportDecision

    container = Container()
    config = container.config()
    container.database.init()

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


async def _enrich_async() -> None:
    """Implementation async de la commande enrich."""
    from loguru import logger as loguru_logger

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

    # Desactiver les logs loguru pendant l'affichage pour eviter le melange
    loguru_logger.disable("src")

    try:
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

    finally:
        # Reactiver les logs
        loguru_logger.enable("src")


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
    from rich.prompt import Prompt
    from rich.status import Status

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

            def extract_series_name(path: Path) -> str | None:
                """Extrait le nom de la serie depuis le chemin du symlink."""
                parts = path.parts
                for i, part in enumerate(parts):
                    if part.lower() in ("séries", "series"):
                        # Le nom de la serie est generalement 2-3 niveaux apres
                        # Ex: Séries/Séries TV/A-M/Breaking Bad/Saison 01/...
                        for j in range(i + 1, min(i + 5, len(parts))):
                            # Ignorer les subdivisions alphabetiques et types
                            if parts[j] in ("Séries TV", "Animation", "Mangas"):
                                continue
                            if len(parts[j]) <= 3 and "-" in parts[j]:
                                continue  # Subdivision A-M, etc.
                            if parts[j].startswith("Saison"):
                                break
                            return parts[j]
                return None

            for i, link in enumerate(broken, 1):
                # Verifier si cette serie doit etre ignoree
                series_name = extract_series_name(link)
                if series_name and series_name in skipped_series:
                    actions.append(RepairAction(link=link, action=RepairActionType.SKIPPED))
                    continue

                # Afficher les infos du lien
                try:
                    original_target = link.readlink()
                except OSError:
                    original_target = Path("<inconnu>")

                console.print(f"\n[dim]({i}/{len(broken)})[/dim]")

                # Chercher des cibles possibles avec recherche floue
                with console.status(f"[cyan]Recherche de candidats pour {link.name}..."):
                    targets_with_scores = repair.find_possible_targets(link, min_score=min_score)

                # Afficher le panel
                panel_content = [
                    f"[bold]{link.name}[/bold]",
                    f"Chemin: {link}",
                    f"Cible originale: [red]{original_target}[/red]",
                ]
                console.print(Panel("\n".join(panel_content), title="Symlink casse"))

                # Affichage pagine des candidats
                page_size = 5
                page_start = 0

                def display_candidates(start: int) -> None:
                    """Affiche une page de candidats."""
                    end = min(start + page_size, len(targets_with_scores))
                    for j, (target, score) in enumerate(targets_with_scores[start:end], start + 1):
                        score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
                        console.print(
                            f"  {j}. [{score_color}]{score:.0f}%[/{score_color}] {target.name}"
                        )
                        console.print(f"     [dim]{target.parent}[/dim]")
                    remaining = len(targets_with_scores) - end
                    if remaining > 0:
                        console.print(f"  [dim]... et {remaining} autre(s) (tapez 'plus' pour voir)[/dim]")

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
                    display_candidates(page_start)

                # Boucle pour gerer la pagination et recherche par titre
                while True:
                    # Prompt interactif avec raccourcis
                    valid_choices = {"r", "s", "i", "q", "t"}  # t = rechercher par titre
                    has_more = targets_with_scores and page_start + page_size < len(targets_with_scores)
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

                            # Detecter le type de media pour filtrer
                            link_str = str(link).lower()
                            is_film = "/films/" in link_str
                            is_series = "/séries/" in link_str or "/series/" in link_str

                            # Recherche dans l'index avec le titre personnalise
                            from difflib import SequenceMatcher
                            custom_clean = repair._extract_clean_title(custom_title)
                            custom_results: list[tuple[Path, float]] = []

                            for candidate_path, candidate_norm, candidate_clean in repair._file_index:
                                # Filtrer par type de media
                                candidate_str = str(candidate_path).lower()
                                if is_film and ("/séries/" in candidate_str or "/series/" in candidate_str):
                                    continue
                                if is_series and "/films/" in candidate_str:
                                    continue

                                # Calculer la similarite avec le titre personnalise (utiliser clean_title)
                                ratio = SequenceMatcher(None, custom_clean, candidate_clean).ratio()
                                score = ratio * 100
                                if score >= min_score:
                                    custom_results.append((candidate_path, score))

                            custom_results.sort(key=lambda x: x[1], reverse=True)
                            custom_results = custom_results[:15]

                            if custom_results:
                                targets_with_scores = custom_results
                                page_start = 0
                                media_label = "films" if is_film else "séries" if is_series else "tous"
                                console.print(f"\n[green]{len(targets_with_scores)}[/green] resultat(s) pour '{custom_title}' ({media_label}):")
                                display_candidates(page_start)
                            else:
                                console.print(f"[red]Aucun resultat pour '{custom_title}'[/red]")
                        continue

                    # Gerer la pagination
                    if choice == "p":
                        page_start += page_size
                        console.print("")
                        display_candidates(page_start)
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

        # Resume
        repaired = sum(1 for a in actions if a.action == RepairActionType.REPAIRED)
        orphaned = sum(1 for a in actions if a.action == RepairActionType.ORPHANED)
        skipped = sum(1 for a in actions if a.action == RepairActionType.SKIPPED)

        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{repaired}[/green] repare(s)")
        console.print(f"  [yellow]{orphaned}[/yellow] deplace(s) vers orphans")
        console.print(f"  [dim]{skipped} ignore(s)[/dim]")

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
