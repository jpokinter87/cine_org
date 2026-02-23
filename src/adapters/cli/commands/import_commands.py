"""
Commandes CLI d'import et d'enrichissement de base (import, enrich, populate-movies, populate-series).
"""

import asyncio
import re
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console


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


# --- Regex pour le parsing des dossiers et fichiers series ---
_SERIES_DIR_RE = re.compile(r"^(.+?)\s*\((\d{4})\)$")
_SEASON_DIR_RE = re.compile(r"^Saison\s+(\d+)$", re.IGNORECASE)
_EPISODE_RE = re.compile(r"S(\d{2,})E(\d{2,})", re.IGNORECASE)
# Format CineOrg : "Titre - SxxExx - Titre Episode - MULTI/MUL/VF/... codec resolution.ext"
_EPISODE_TITLE_RE = re.compile(
    r"S\d{2,}E\d{2,}\s*-\s*(.+?)\s*-\s*(?:MUL|VF|VO|FR|EN|MULTI|FRENCH|CUSTOM)",
    re.IGNORECASE,
)


def populate_series(
    source_dir: Annotated[
        Optional[Path],
        typer.Argument(help="Repertoire video racine (contient Séries/ avec symlinks)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de series a traiter (0 = illimite)",
        ),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
) -> None:
    """Peuple les tables series et episodes depuis les symlinks video."""
    asyncio.run(_populate_series_async(source_dir, limit, dry_run))


@with_container()
async def _populate_series_async(
    container, source_dir: Optional[Path], limit: int, dry_run: bool
) -> None:
    """Implementation async de la commande populate-series."""
    from src.core.entities.media import Series
    from src.utils.constants import VIDEO_EXTENSIONS

    config = container.config()
    series_repo = container.series_repository()
    episode_repo = container.episode_repository()

    # Par defaut, scanner video_dir (symlinks au format CineOrg)
    base_dir = source_dir or Path(config.video_dir)
    series_root = base_dir / "Séries"

    if not series_root.exists():
        console.print(f"[red]Erreur:[/red] Repertoire introuvable: {series_root}")
        raise typer.Exit(code=1)

    if dry_run:
        console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

    console.print(f"[bold cyan]Population des tables series/episodes[/bold cyan]: {series_root}\n")

    with suppress_loguru():
        # Phase 1 : decouvrir tous les dossiers serie
        series_dirs = _discover_series_dirs(series_root)

        if limit > 0:
            series_dirs = series_dirs[:limit]

        console.print(f"[dim]{len(series_dirs)} dossier(s) serie detecte(s)[/dim]\n")

        series_created = 0
        series_skipped = 0
        episodes_created = 0
        episodes_skipped = 0
        errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Traitement...", total=len(series_dirs))

            for series_path, title, year in series_dirs:
                progress.update(task, description=f"[cyan]{title}")

                try:
                    # Verifier si la serie existe deja (titre exact + annee)
                    existing = series_repo.search_by_title(title, year=year)
                    exact_match = next(
                        (s for s in existing if s.title == title and s.year == year),
                        None,
                    )

                    if exact_match:
                        series_id = exact_match.id
                        series_skipped += 1
                    else:
                        series_entity = Series(title=title, year=year)
                        if not dry_run:
                            saved = series_repo.save(series_entity)
                            series_id = saved.id
                        else:
                            series_id = None
                        series_created += 1

                    # Phase 2 : scanner les episodes
                    ep_created, ep_skipped, ep_errors = _process_episodes(
                        series_path=series_path,
                        series_id=series_id,
                        episode_repo=episode_repo,
                        video_extensions=VIDEO_EXTENSIONS,
                        dry_run=dry_run,
                    )
                    episodes_created += ep_created
                    episodes_skipped += ep_skipped
                    errors += ep_errors

                except Exception as e:
                    console.print(f"\n[red]Erreur[/red] {title}: {e}")
                    errors += 1

                progress.advance(task)

    # Resume final
    console.print(f"\n[bold]Resume:[/bold]")
    console.print(f"  [green]{series_created}[/green] serie(s) creee(s)")
    console.print(f"  [yellow]{series_skipped}[/yellow] serie(s) deja en base")
    console.print(f"  [green]{episodes_created}[/green] episode(s) cree(s)")
    console.print(f"  [yellow]{episodes_skipped}[/yellow] episode(s) deja en base")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")


def _discover_series_dirs(series_root: Path) -> list[tuple[Path, str, int | None]]:
    """
    Decouvre tous les dossiers serie sous le repertoire racine.

    Parcourt recursivement les sous-categories (Animation, Séries TV, etc.)
    et detecte les dossiers contenant un sous-dossier 'Saison'.

    Retourne une liste de (chemin, titre, annee).
    """
    results: list[tuple[Path, str, int | None]] = []

    for category_dir in sorted(series_root.iterdir()):
        if not category_dir.is_dir():
            continue
        _find_series_in_dir(category_dir, results)

    results.sort(key=lambda x: x[1].lower())
    return results


def _find_series_in_dir(
    directory: Path, results: list[tuple[Path, str, int | None]]
) -> None:
    """
    Recherche recursivement les dossiers serie dans un repertoire.

    Un dossier est considere comme une serie s'il contient au moins
    un sous-dossier 'Saison XX'.
    """
    try:
        children = sorted(directory.iterdir())
    except PermissionError:
        return

    has_season = any(
        child.is_dir() and _SEASON_DIR_RE.match(child.name) for child in children
    )

    if has_season:
        match = _SERIES_DIR_RE.match(directory.name)
        if match:
            title = match.group(1).strip()
            year = int(match.group(2))
        else:
            title = directory.name.strip()
            year = None
        results.append((directory, title, year))
    else:
        for child in children:
            if child.is_dir():
                _find_series_in_dir(child, results)


def _resolve_symlink_target(path: Path) -> str | None:
    """Resout la cible d'un symlink, retourne le chemin absolu ou None."""
    if path.is_symlink():
        try:
            target = path.resolve()
            if target.exists():
                return str(target)
        except (OSError, ValueError):
            pass
    return None


def _process_episodes(
    series_path: Path,
    series_id: str | None,
    episode_repo,
    video_extensions: frozenset[str],
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Traite les episodes d'un dossier serie.

    Scanne les symlinks et resout leurs cibles pour stocker file_path.
    Retourne (crees, ignores, erreurs).
    """
    created = 0
    skipped = 0
    errors = 0

    from src.core.entities.media import Episode
    from src.infrastructure.persistence.models import EpisodeModel

    for season_dir in sorted(series_path.iterdir()):
        if not season_dir.is_dir():
            continue
        season_match = _SEASON_DIR_RE.match(season_dir.name)
        if not season_match:
            continue
        season_num = int(season_match.group(1))

        for video_file in sorted(season_dir.iterdir()):
            # Accepter fichiers reels et symlinks
            if not (video_file.is_file() or video_file.is_symlink()):
                continue
            if video_file.suffix.lower() not in video_extensions:
                continue

            ep_match = _EPISODE_RE.search(video_file.name)
            if not ep_match:
                errors += 1
                continue

            ep_num = int(ep_match.group(2))

            # Titre d'episode (format CineOrg)
            ep_title = ""
            title_match = _EPISODE_TITLE_RE.search(video_file.name)
            if title_match:
                ep_title = title_match.group(1).strip()

            # Resoudre la cible du symlink pour file_path
            file_path = _resolve_symlink_target(video_file)
            if file_path is None and video_file.is_file():
                file_path = str(video_file.resolve())

            # Deduplication par series_id + season + episode
            if series_id is not None:
                existing_eps = episode_repo.get_by_series(
                    series_id, season=season_num, episode=ep_num
                )
                if existing_eps:
                    skipped += 1
                    continue

            episode = Episode(
                series_id=series_id,
                season_number=season_num,
                episode_number=ep_num,
                title=ep_title,
            )

            if not dry_run and series_id is not None:
                try:
                    # Sauvegarder avec file_path via le modele directement
                    model = episode_repo._to_model(episode)
                    model.file_path = file_path
                    episode_repo._session.add(model)
                    episode_repo._session.commit()
                    created += 1
                except Exception:
                    errors += 1
            else:
                created += 1

    return created, skipped, errors
