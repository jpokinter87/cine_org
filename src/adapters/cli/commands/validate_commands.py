"""
Commandes CLI de validation des fichiers video (validate auto/manual/batch/file).
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.prompt import Confirm

from src.adapters.cli.auto_validator import auto_validate_files, ValidationResult
from src.adapters.cli.helpers import with_container
from src.adapters.cli.validation import (
    console,
    display_batch_summary,
    execute_batch_transfer,
    validation_loop,
)
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
    tvdb_client = container.tvdb_client()
    pending_list = service.list_pending()

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente de validation manuelle.[/yellow]")
        return

    # Etape 1: Auto-validation par score, duree et episodes (delegue a auto_validator)
    result: ValidationResult = await auto_validate_files(
        pending_list, service, tmdb_client, tvdb_client
    )

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
