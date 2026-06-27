"""Commande CLI relink-movies : ré-association des fiches films sans fichier."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from src.adapters.cli.validation import console
from src.container import Container
from src.services.relink_service import (
    MovieFileFinder,
    MovieRelinkService,
    RelinkOutcome,
    TmdbAltTitleProvider,
)


_STATUS_STYLES = {
    "linked_existing": "green",
    "linked_created": "green",
    "unresolved": "yellow",
    "already_linked": "dim",
    "error": "red",
}


def relink_movies(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Effectuer la ré-association (par défaut : dry-run).",
        ),
    ] = False,
    min_score: Annotated[
        float,
        typer.Option(
            "--min-score",
            help="Score canonique minimum (titre/année/durée) pour lier en tier 2 (0-100).",
        ),
    ] = 85.0,
    suggest: Annotated[
        bool,
        typer.Option(
            "--suggest",
            help="Après les liens sûrs, proposer interactivement les cas litigieux.",
        ),
    ] = False,
    floor: Annotated[
        float,
        typer.Option(
            "--floor",
            help="Score plancher des suggestions litigieuses (avec --suggest).",
        ),
    ] = 60.0,
) -> None:
    """Renseigne file_path/symlink_path des fiches films sans fichier.

    Par défaut en dry-run. Ajouter --execute pour appliquer.

    Stratégie : (1) réutilise un symlink formaté déjà présent dans video/,
    (2) sinon retrouve le fichier brut dans storage/ par scoring canonique
    (titre + année + durée, seuil 85) et crée un symlink au nom canonique.
    La durée écarte featurettes et mauvais films de même année. Les vraies
    coquilles vides restent intactes.

    --suggest : après application des liens sûrs (≥ seuil), propose pour chaque
    fiche restante les candidats de la bande litigieuse (floor ≤ score < seuil),
    à choisir à la main. Implique l'exécution (écrit les liens choisis).
    """
    from loguru import logger as loguru_logger
    from rich.status import Status

    container = Container()
    config = container.config()
    container.database.init()

    video_dir = Path(config.video_dir)
    storage_dir = Path(config.storage_dir)

    session = container.session()
    extractor = container.media_info_extractor()
    parser = container.filename_parser()
    repair = container.repair_service(
        storage_dir=storage_dir,
        video_dir=video_dir,
        trash_dir=storage_dir / ".trash",
        db_session=session,
    )

    # Provider de titres alternatifs (AKA) via TMDB, préchargé pour les fiches NULL
    alt_provider = None
    try:
        from src.infrastructure.persistence.models import MovieModel
        from sqlmodel import select

        tmdb_ids = session.exec(
            select(MovieModel.tmdb_id).where(
                MovieModel.file_path.is_(None), MovieModel.tmdb_id.is_not(None)
            )
        ).all()
        if tmdb_ids:
            alt_provider = TmdbAltTitleProvider(container.tmdb_client())
            with Status(
                "[cyan]Récupération des titres alternatifs (TMDB)...", console=console
            ):
                alt_provider.prefetch([int(t) for t in tmdb_ids])
    except Exception:
        alt_provider = None

    # --suggest est une session d'actions explicites : on exécute les liens.
    if suggest:
        execute = True

    mode = "EXÉCUTION" if execute else "DRY-RUN"
    console.print(
        f"[bold cyan]Ré-association des fiches sans fichier — {mode}[/bold cyan]\n"
    )

    loguru_logger.disable("src")
    try:
        with Status(
            f"[cyan]Indexation du stockage ({storage_dir})...", console=console
        ) as status:
            count = repair.build_file_index(
                progress_callback=lambda n, _msg: status.update(
                    f"[cyan]Indexation du stockage : {n} fichiers..."
                )
            )
        console.print(f"[dim]Index : {count} fichiers dans {storage_dir}[/dim]\n")

        finder = MovieFileFinder(
            video_dir,
            repair,
            parser,
            extractor,
            min_score=min_score,
            alt_title_provider=alt_provider,
        )
        service = MovieRelinkService(session, extractor, finder, video_dir)

        with Status("[cyan]Recherche des fichiers...", console=console):
            outcomes = service.relink_unlinked(dry_run=not execute)
    finally:
        loguru_logger.enable("src")

    _print_results(outcomes, execute=execute)

    if suggest:
        unresolved_ids = [o.movie_id for o in outcomes if o.status == "unresolved"]
        loguru_logger.disable("src")
        try:
            _run_suggestions(service, session, unresolved_ids, floor)
        finally:
            loguru_logger.enable("src")

    session.close()


def _duration_min(media_info) -> str:
    """Durée d'un MediaInfo en minutes, ou '?'."""
    dur = getattr(media_info, "duration_seconds", None) if media_info else None
    return f"{round(dur / 60)} min" if dur else "? min"


def _preview(path: Path) -> None:
    """Lance une prévisualisation locale du fichier (mpv / lecteur configuré)."""
    import subprocess

    try:
        from src.player_profiles import get_active_profile

        profile = get_active_profile() or {}
        command = profile.get("command", "mpv")
    except Exception:
        command = "mpv"
    try:
        subprocess.Popen(
            [command, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.print(
            f"[dim]▶ Lecture lancée ({command}). Ferme le lecteur pour continuer.[/dim]"
        )
    except FileNotFoundError:
        console.print(f"[red]Lecteur introuvable : {command}[/red]")


def _display_candidates(candidates) -> None:
    for i, c in enumerate(candidates, 1):
        console.print(
            f"  {i}. [yellow]score {c.score:.0f}[/yellow]  "
            f"{Path(c.storage_path).name}  [dim]({_duration_min(c.media_info)})[/dim]"
        )


def _resolve_one(service, movie, floor: float) -> str:
    """Boucle interactive pour une fiche. Retourne 'linked' | 'skip' | 'quit'."""
    candidates = service.collect_suggestions(movie.id, floor=floor)

    dur_decl = round(movie.duration_seconds / 60) if movie.duration_seconds else "?"
    console.print(
        f"\n[bold]{movie.title} ({movie.year})[/bold]  "
        f"[dim]durée déclarée : {dur_decl} min[/dim]"
    )

    while True:
        if candidates:
            _display_candidates(candidates)
        else:
            console.print("  [dim]aucun candidat automatique[/dim]")

        prompt = (
            "Choix [numéro=lier, v<n>=visionner, t=titre manuel, "
            "Entrée=passer, q=quitter] : "
        )
        choice = input(prompt).strip().lower()

        if choice == "":
            console.print("[dim]Passé[/dim]")
            return "skip"
        if choice == "q":
            return "quit"
        if choice == "t":
            title = input("Titre à rechercher : ").strip()
            if title:
                candidates = service.manual_search(movie.id, title)
                if not candidates:
                    console.print("[dim]Aucun candidat pour ce titre[/dim]")
            continue
        if choice.startswith("v") and choice[1:].isdigit():
            n = int(choice[1:])
            if 1 <= n <= len(candidates):
                _preview(Path(candidates[n - 1].storage_path))
            continue
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(candidates):
                chosen = candidates[n - 1]
                outcome = service.link_chosen(
                    movie.id,
                    chosen.storage_path,
                    media_info=chosen.media_info,
                    dry_run=False,
                )
                if outcome.status == "linked_created":
                    console.print(f"[green]✓ Lié → {outcome.symlink_path}[/green]")
                    return "linked"
                console.print(f"[red]Échec : {outcome.reason or outcome.status}[/red]")
                return "skip"
        console.print("[dim]Entrée invalide[/dim]")


def _run_suggestions(service, session, unresolved_ids: list[int], floor: float) -> None:
    """Passe interactive sur toutes les fiches non résolues."""
    from src.infrastructure.persistence.models import MovieModel

    console.print(
        "\n[bold cyan]Suggestions — cas litigieux à valider à la main[/bold cyan]"
    )

    linked = 0
    for mid in unresolved_ids:
        movie = session.get(MovieModel, mid)
        if movie is None:
            continue
        result = _resolve_one(service, movie, floor)
        if result == "linked":
            linked += 1
        elif result == "quit":
            break

    console.print(f"\n[bold]Suggestions appliquées : {linked}[/bold]")


def _print_results(outcomes: list[RelinkOutcome], execute: bool) -> None:
    """Affiche les résultats sous forme de table + résumé."""
    if not outcomes:
        console.print("[green]Aucune fiche sans fichier.[/green]")
        return

    table = Table(show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Statut")
    table.add_column("Fichier / Symlink", overflow="fold")

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
        style = _STATUS_STYLES.get(o.status, "")
        status_cell = f"[{style}]{o.status}[/{style}]" if style else o.status
        detail = ""
        if o.symlink_path:
            detail = str(o.symlink_path)
        elif o.reason:
            detail = o.reason
        table.add_row(str(o.movie_id), status_cell, detail)

    console.print(table)
    console.print()

    summary_bits = []
    for status in (
        "linked_existing",
        "linked_created",
        "unresolved",
        "already_linked",
        "error",
    ):
        n = counts.get(status, 0)
        if n:
            style = _STATUS_STYLES.get(status, "")
            tag = f"[{style}]{n}[/{style}]" if style else str(n)
            summary_bits.append(f"{tag} {status}")
    console.print("  ".join(summary_bits))

    linked = counts.get("linked_existing", 0) + counts.get("linked_created", 0)
    if not execute and linked:
        console.print(
            "\n[dim]Relancer avec --execute pour appliquer les ré-associations.[/dim]"
        )
