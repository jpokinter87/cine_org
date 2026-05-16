"""
Sous-commande `migrate-nas review` : review interactive des items en attente.

Itère sur les 4 buckets non-MIGRATE (needs_validation, unrated, low_rated,
already_in_library), affiche une carte Rich par item, prompt l'utilisateur
pour une décision. Décisions persistées dans state_store, consultables
ensuite par `migrate-nas apply`.

Reprise via --resume (skippe les items déjà décidés).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from src.adapters.cli.validation import console
from src.services.migration.dataclasses import Bucket, MigrationItem


def review_command(
    plan_path: Annotated[
        Path,
        typer.Argument(help="Chemin du plan JSON produit par `plan`."),
    ],
    bucket: Annotated[
        Optional[str],
        typer.Option(
            "--bucket",
            help=(
                "Filtre sur un bucket précis (needs_validation, unrated, "
                "low_rated, already_in_library). Défaut : tous."
            ),
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--restart",
            help=(
                "Reprend en sautant les items déjà décidés (défaut). "
                "--restart force le re-traitement de tous."
            ),
        ),
    ] = True,
    state_store: Annotated[
        Optional[Path],
        typer.Option(
            "--state-store",
            help="Chemin du journal SQLite (défaut: <plan>.state.sqlite).",
        ),
    ] = None,
) -> None:
    """Review interactive des items en attente (4 buckets non-MIGRATE)."""
    state_path = state_store or plan_path.with_suffix(
        plan_path.suffix + ".state.sqlite"
    )
    try:
        bucket_filter = Bucket(bucket) if bucket else None
    except ValueError as e:
        valid = ", ".join(b.value for b in Bucket)
        raise typer.BadParameter(
            f"Bucket invalide : '{bucket}'. Valeurs autorisées : {valid}",
            param_hint="--bucket",
        ) from e
    console.print(
        f"[bold cyan]Review[/bold cyan] depuis [yellow]{plan_path}[/yellow] "
        f"(state: [dim]{state_path}[/dim], "
        f"bucket: {bucket_filter.value if bucket_filter else 'tous'}, "
        f"resume: {resume})"
    )
    # TODO Task 9 : interactive loop
    console.print("[yellow]Pas encore implémenté — Task 9 fournit la loop.[/yellow]")


def render_review_card(
    console: Console,
    item: MigrationItem,
    *,
    position: tuple[int, int],
) -> None:
    """Affiche une carte Rich pour un item en attente.

    Format :
        ┌─ [N/total] bucket • media_root ─────────────┐
        │ Source : <path> (size MB)                    │
        │ Top candidates TMDB :                        │
        │   1. Title (year) score N                    │
        └──────────────────────────────────────────────┘
    """
    pos_n, pos_total = position
    bucket = item.bucket.value
    title_line = f"[{pos_n}/{pos_total}] {bucket} • {item.media_root or '?'}"

    size_mb = (item.size_bytes or 0) / (1024**2)
    body_lines = [
        f"[dim]Source :[/dim] {item.symlink_path}  ({size_mb:.0f} MB)",
    ]

    if item.bucket == Bucket.NEEDS_VALIDATION:
        body_lines.append("")
        body_lines.append("[bold]Top candidates TMDB :[/bold]")
        for i, c in enumerate(item.match.top_candidates[:5], start=1):
            title = c.get("title", "?")
            year = c.get("year", "?")
            score = c.get("score", 0.0)
            body_lines.append(
                f"  {i}. {title:<40} ({year}) score {score:.0f}"
            )
    elif item.bucket == Bucket.UNRATED:
        body_lines.append("[yellow]Note absente — décider de migrer.[/yellow]")
    elif item.bucket == Bucket.LOW_RATED:
        rating_value = item.rating.value
        rating_str = f"{rating_value:.1f}" if rating_value is not None else "?"
        body_lines.append(
            f"[yellow]Note {rating_str} (< seuil) — décider de migrer.[/yellow]"
        )
    elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
        existing = next(
            (t.split(":", 1)[1] for t in item.tags if t.startswith("existing:")),
            "?",
        )
        body_lines.append(f"[cyan]Doublon — existe déjà :[/cyan] {existing}")

    console.print(
        Panel(
            "\n".join(body_lines),
            title=title_line,
            border_style="cyan",
        )
    )
