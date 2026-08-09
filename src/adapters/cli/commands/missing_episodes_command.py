"""
Commande CLI `missing-episodes`.

Aplatit les verdicts de complétude en un inventaire des manques, enrichi de
la qualité à rechercher, pour préparer une session de mise à jour.
"""

from pathlib import Path
from typing import Annotated, Optional

import typer

from src.adapters.cli.validation import console
from src.infrastructure.persistence.database import get_session
from src.services.completeness.missing_export import (
    build_missing_entries,
    format_entries,
)


def missing_episodes(
    series_id: Annotated[
        Optional[int],
        typer.Option(
            "--series-id",
            help="Limiter l'inventaire à une seule série (ID interne)",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="text (une ligne par manque) ou csv (détail complet)",
        ),
    ] = "text",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Écrire dans un fichier au lieu de la sortie standard",
        ),
    ] = None,
) -> None:
    """Liste les épisodes manquants et la qualité dans laquelle les chercher."""
    if output_format not in ("text", "csv"):
        console.print(
            f"[red]Format inconnu :[/red] {output_format} (attendu : text ou csv)"
        )
        raise typer.Exit(code=1)

    session = next(get_session())
    try:
        entries = build_missing_entries(
            session, series_ids=[series_id] if series_id is not None else None
        )
    finally:
        session.close()

    if not entries:
        console.print(
            "[green]Aucun manque à signaler.[/green] "
            "(Les verdicts datent de la dernière exécution de check-completeness.)"
        )
        return

    content = format_entries(entries, output_format)

    if output:
        output.write_text(content + "\n", encoding="utf-8")
        series_count = len({e.series_title for e in entries})
        console.print(
            f"[green]✓[/green] {len(entries)} manque(s) sur {series_count} série(s) "
            f"écrit(s) dans [bold]{output}[/bold]"
        )
        return

    # Sortie brute (sans balisage Rich) : le contenu est fait pour être
    # redirigé vers un fichier ou collé ailleurs tel quel.
    try:
        print(content)
    except BrokenPipeError:
        # Sortie tronquée par un `| head` : rien à signaler.
        pass
