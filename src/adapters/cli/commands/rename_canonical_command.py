"""Commande CLI rename-canonical : renommage des fichiers vers le titre DB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from src.adapters.cli.validation import console
from src.container import Container
from src.services.canonical_renamer import (
    CanonicalRenamerService,
    RenameOutcome,
)


_STATUS_STYLES = {
    "renamed": "green",
    "already_canonical": "dim",
    "file_missing": "red",
    "conflict": "yellow",
    "no_file_path": "dim",
    "error": "red",
}


def rename_canonical(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Effectuer le renommage (par défaut : dry-run).",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Nombre maximum de films à traiter.",
        ),
    ] = 20,
    movie_id: Annotated[
        Optional[int],
        typer.Option(
            "--movie-id",
            help="Cibler un seul film par son ID (ignore --from-cache).",
        ),
    ] = None,
    from_cache: Annotated[
        Optional[Path],
        typer.Option(
            "--from-cache",
            help="Fichier JSON de résultats d'un scan d'associations suspectes.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Renomme les fichiers films vers leur nom canonique issu de la DB.

    Par défaut en dry-run. Ajouter --execute pour effectuer le renommage.

    Réutilise RenamerService pour construire le nom cible et préserve les
    hardlinks de seeding (os.rename sur storage conserve l'inode).
    """
    container = Container()
    container.database.init()

    # Déterminer les IDs cibles
    if movie_id is not None:
        movie_ids = [movie_id]
    elif from_cache is not None:
        movie_ids = _ids_from_cache(from_cache, limit)
    else:
        console.print(
            "[red]Spécifier --movie-id ou --from-cache.[/red]"
        )
        raise typer.Exit(1)

    if not movie_ids:
        console.print("[dim]Aucun film à traiter.[/dim]")
        return

    mode = "EXÉCUTION" if execute else "DRY-RUN"
    console.print(
        f"[bold cyan]Renommage canonique — {mode}[/bold cyan]  "
        f"({len(movie_ids)} film(s))\n"
    )

    session = container.session()
    extractor = container.media_info_extractor()
    service = CanonicalRenamerService(session, extractor)

    outcomes = service.rename_movies(movie_ids, dry_run=not execute)

    _print_results(outcomes, execute=execute)

    session.close()


def _ids_from_cache(cache_file: Path, limit: int) -> list[int]:
    """Charge les movie_ids depuis un cache de scan d'associations suspectes."""
    data = json.loads(cache_file.read_text())
    results = data.get("results", [])
    ids = [
        r["entity_id"]
        for r in results
        if r.get("entity_type") == "movie" and r.get("entity_id")
    ]
    return ids[:limit]


def _print_results(outcomes: list[RenameOutcome], execute: bool) -> None:
    """Affiche les résultats sous forme de table + résumé."""
    table = Table(show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Statut")
    table.add_column("Actuel", overflow="fold")
    table.add_column("→ Canonique", overflow="fold")

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
        style = _STATUS_STYLES.get(o.status, "")
        status_cell = f"[{style}]{o.status}[/{style}]" if style else o.status
        old = o.old_name or (o.reason or "")
        new = o.new_name or ""
        if o.status == "conflict" and o.reason:
            new = f"{new}   [yellow]({o.reason})[/yellow]"
        table.add_row(str(o.movie_id), status_cell, old, new)

    console.print(table)
    console.print()

    # Résumé
    summary_bits = []
    for status in ("renamed", "already_canonical", "conflict", "file_missing",
                   "no_file_path", "error"):
        n = counts.get(status, 0)
        if n:
            style = _STATUS_STYLES.get(status, "")
            tag = f"[{style}]{n}[/{style}]" if style else str(n)
            summary_bits.append(f"{tag} {status}")

    console.print("  ".join(summary_bits))

    if not execute and counts.get("renamed", 0):
        console.print(
            "\n[dim]Relancer avec --execute pour effectuer les renommages.[/dim]"
        )
