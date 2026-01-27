"""
Commandes Typer pour la validation des fichiers video.

Ce module fournit les commandes CLI:
- validate auto: Validation automatique (score >= 85% et candidat unique)
- validate manual: Validation manuelle interactive
- validate batch: Execution du batch de transferts pour les fichiers valides
"""

import asyncio
from pathlib import Path

import typer
from rich.prompt import Confirm

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
            # Pour les series: extraire saison/episode de media_info.guessed
            guessed = media_info.guessed if media_info else {}
            if guessed is None:
                guessed = {}

            season_num = guessed.get("season", 1)
            episode_num = guessed.get("episode", 1)
            episode_title = guessed.get("episode_title", "")

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
