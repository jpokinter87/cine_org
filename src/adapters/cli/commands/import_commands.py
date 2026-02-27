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
        console.print(
            f"[bold cyan]Import de la videotheque[/bold cyan]: {source_dir}\n"
        )
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

    console.print(
        f"[bold cyan]Enrichissement API[/bold cyan]: {len(pending)} fichier(s)\n"
    )

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
                    best_score = (
                        item.candidates[0].get("score", 0) if item.candidates else 0
                    )
                    console.print(
                        f"[dim]({i}/{len(pending)})[/dim] [green]{filename}[/green] ✓ {len(item.candidates)} candidat(s), score: {best_score:.0f}%"
                    )
                else:
                    console.print(
                        f"[dim]({i}/{len(pending)})[/dim] [green]{filename}[/green] ✓"
                    )
                enriched_count += 1
            else:
                # Afficher en rouge
                console.print(
                    f"[dim]({i}/{len(pending)})[/dim] [red]{filename}[/red] ✗"
                )
                failed_count += 1

        # Afficher le resume
        console.print(
            f"\n[bold]Resume:[/bold] [green]{enriched_count}[/green] enrichi(s), [red]{failed_count}[/red] echec(s)"
        )


def populate_movies(
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
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
                source = (
                    first_candidate.get("source")
                    if isinstance(first_candidate, dict)
                    else getattr(first_candidate, "source", None)
                )
                if source == "tmdb":
                    validated_movies.append(p)
            if limit > 0 and len(validated_movies) >= limit:
                break

        if not validated_movies:
            console.print("[yellow]Aucun film valide a traiter.[/yellow]")
            console.print(
                "[dim]Utilisez 'process' ou 'pending' pour valider des films.[/dim]"
            )
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
                    console.print(
                        f"[dim]({i}/{len(validated_movies)})[/dim] {filename} - deja en base"
                    )
                    updated += 1
                    continue

                # Recuperer les details depuis TMDB
                details = await tmdb_client.get_details(tmdb_id)

                if not details:
                    console.print(
                        f"[dim]({i}/{len(validated_movies)})[/dim] [red]{filename}[/red] - TMDB introuvable"
                    )
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

                console.print(
                    f"[dim]({i}/{len(validated_movies)})[/dim] [green]{filename}[/green] -> {details.title} ({details.year})"
                )
                created += 1

                # Rate limiting
                await asyncio.sleep(0.25)

            except Exception as e:
                console.print(
                    f"[dim]({i}/{len(validated_movies)})[/dim] [red]{filename}[/red] - Erreur: {e}"
                )
                errors += 1

        # Resume
        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{created}[/green] film(s) cree(s)")
        console.print(f"  [yellow]{updated}[/yellow] deja en base")
        if errors > 0:
            console.print(f"  [red]{errors}[/red] erreur(s)")

        if not dry_run and created > 0:
            console.print(
                "\n[dim]Utilisez 'enrich-ratings' pour enrichir les notes TMDB.[/dim]"
            )

        if tmdb_client:
            await tmdb_client.close()


# --- Commande link-movies ---
_FILM_NAME_RE = re.compile(r"^(.+?)\s*\((\d{4})\)")


def _normalize_for_match(title: str) -> str:
    """Normalise un titre pour comparaison : sans accents, minuscules, sans articles."""
    import unicodedata

    # Supprimer les accents (NFD decomposition puis filtrage des combining chars)
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    result = ascii_str.lower().strip()
    # Supprimer les articles en début de titre
    result = re.sub(
        r"^(l'|le |la |les |the |a |an |un |une |des |das |der |die |el |los |las )",
        "",
        result,
    )
    return result.strip()


def link_movies(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
) -> None:
    """Associe les films en base a leurs fichiers physiques via les symlinks video/."""
    asyncio.run(_link_movies_async(dry_run))


@with_container()
async def _link_movies_async(container, dry_run: bool) -> None:
    """Implementation async de link-movies avec matching progressif."""
    from difflib import SequenceMatcher

    from sqlmodel import select

    from src.infrastructure.persistence.models import MovieModel
    from src.utils.constants import VIDEO_EXTENSIONS

    config = container.config()
    movie_repo = container.movie_repository()
    session = movie_repo._session

    video_films_dir = Path(config.video_dir) / "Films"
    if not video_films_dir.exists():
        console.print(f"[red]Erreur:[/red] Repertoire introuvable: {video_films_dir}")
        raise typer.Exit(code=1)

    def _try_match_movie(
        file_title: str,
        year: int,
        movies_by_year: dict[int, list[tuple[str, str | None, "MovieModel"]]],
    ) -> tuple["MovieModel | None", str]:
        """Cherche un film par matching progressif. Retourne (movie, methode)."""
        candidates = movies_by_year.get(year, [])
        if not candidates:
            return None, ""

        norm_file = _normalize_for_match(file_title)

        # 1. Match normalisé exact
        for norm_title, norm_original, movie in candidates:
            if movie.file_path:
                continue
            if norm_file == norm_title or (norm_original and norm_file == norm_original):
                return movie, "normalized"

        # 2. Match par sous-titre (fichier contient " - " avec sous-titre)
        if "  -  " in file_title or " - " in file_title:
            separator = "  -  " if "  -  " in file_title else " - "
            main_title = file_title.split(separator)[0].strip()
            norm_main = _normalize_for_match(main_title)
            for norm_title, norm_original, movie in candidates:
                if movie.file_path:
                    continue
                if norm_main == norm_title or (
                    norm_original and norm_main == norm_original
                ):
                    return movie, "substring"

        # 3. Match par contenu (titre DB contenu dans nom fichier ou inversement)
        for norm_title, norm_original, movie in candidates:
            if movie.file_path:
                continue
            if len(norm_title) >= 5 and (
                norm_title in norm_file or norm_file in norm_title
            ):
                return movie, "contains"
            if (
                norm_original
                and len(norm_original) >= 5
                and (norm_original in norm_file or norm_file in norm_original)
            ):
                return movie, "contains"

        # 4. Match fuzzy (SequenceMatcher >= 0.85)
        best_ratio = 0.0
        best_movie = None
        for norm_title, norm_original, movie in candidates:
            if movie.file_path:
                continue
            ratio = SequenceMatcher(None, norm_file, norm_title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_movie = movie
            if norm_original:
                ratio_orig = SequenceMatcher(None, norm_file, norm_original).ratio()
                if ratio_orig > best_ratio:
                    best_ratio = ratio_orig
                    best_movie = movie
        if best_ratio >= 0.85 and best_movie and not best_movie.file_path:
            return best_movie, "fuzzy"

        return None, ""

    with suppress_loguru():
        # --- Pre-charger l'index des films sans file_path par annee ---
        all_movies_no_fp = session.exec(
            select(MovieModel).where(MovieModel.file_path.is_(None))
        ).all()
        movies_by_year: dict[int, list[tuple[str, str | None, MovieModel]]] = {}
        for movie in all_movies_no_fp:
            if movie.year:
                entry = (
                    _normalize_for_match(movie.title),
                    _normalize_for_match(movie.original_title)
                    if movie.original_title
                    else None,
                    movie,
                )
                movies_by_year.setdefault(movie.year, []).append(entry)

        initial_no_fp = len(all_movies_no_fp)

        # Lister tous les symlinks video dans Films/
        symlinks = [
            f
            for f in video_films_dir.rglob("*")
            if f.is_symlink() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]

        console.print(
            f"[bold cyan]Association films ↔ fichiers[/bold cyan]: "
            f"{len(symlinks)} symlinks, {initial_no_fp} films sans fichier\n"
        )

        if dry_run:
            console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

        # Compteurs par methode
        stats = {"exact": 0, "normalized": 0, "substring": 0, "contains": 0, "fuzzy": 0}
        already = 0
        not_found = 0
        no_target = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "[cyan]Passe 1 — symlinks...", total=len(symlinks)
            )

            for symlink in symlinks:
                m = _FILM_NAME_RE.match(symlink.name)
                if not m:
                    progress.advance(task)
                    continue

                title = m.group(1).strip()
                year = int(m.group(2))

                # Resoudre la cible du symlink
                try:
                    target = symlink.resolve()
                    if not target.exists():
                        no_target += 1
                        progress.advance(task)
                        continue
                except (OSError, ValueError):
                    no_target += 1
                    progress.advance(task)
                    continue

                file_path = str(target)

                # Matching progressif via l'index en memoire
                movie, method = _try_match_movie(title, year, movies_by_year)

                if not movie:
                    not_found += 1
                    progress.advance(task)
                    continue

                if movie.file_path:
                    already += 1
                    progress.advance(task)
                    continue

                progress.update(task, description=f"[cyan]{title}")

                if not dry_run:
                    movie.file_path = file_path
                    session.add(movie)
                    session.commit()

                stats[method] += 1
                progress.advance(task)

    # --- Passe 2 : recherche dans storage/ pour les films encore sans file_path ---
    storage_stats = {"exact": 0, "normalized": 0, "substring": 0, "contains": 0, "fuzzy": 0}
    storage_films_dir = Path(config.storage_dir) / "Films"
    if storage_films_dir.exists():
        # Recharger les films encore sans file_path
        movies_no_fp = session.exec(
            select(MovieModel).where(MovieModel.file_path.is_(None))
        ).all()

        if movies_no_fp:
            console.print(
                f"\n[bold cyan]Passe 2 — recherche dans storage/[/bold cyan]: "
                f"{len(movies_no_fp)} films encore sans fichier\n"
            )

            # Reconstruire l'index des films sans file_path
            movies_by_year_2: dict[int, list[tuple[str, str | None, MovieModel]]] = {}
            for movie in movies_no_fp:
                if movie.year:
                    entry = (
                        _normalize_for_match(movie.title),
                        _normalize_for_match(movie.original_title)
                        if movie.original_title
                        else None,
                        movie,
                    )
                    movies_by_year_2.setdefault(movie.year, []).append(entry)

            # Index des fichiers storage par (titre, annee, path)
            storage_entries: list[tuple[str, int, Path]] = []
            for f in storage_films_dir.rglob("*"):
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                    fm = _FILM_NAME_RE.match(f.name)
                    if fm:
                        storage_entries.append(
                            (fm.group(1).strip(), int(fm.group(2)), f)
                        )

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "[cyan]Recherche storage...", total=len(storage_entries)
                )

                for file_title, year, file_path_obj in storage_entries:
                    movie, method = _try_match_movie(
                        file_title, year, movies_by_year_2
                    )

                    if movie and not movie.file_path:
                        progress.update(
                            task, description=f"[cyan]{movie.title}"
                        )
                        if not dry_run:
                            movie.file_path = str(file_path_obj)
                            session.add(movie)
                            session.commit()
                        storage_stats[method] += 1

                    progress.advance(task)
    else:
        console.print(
            f"\n[dim]Storage non trouvé: {storage_films_dir} — passe 2 ignorée[/dim]"
        )

    # Resume detaille
    total_linked = sum(stats.values())
    total_storage = sum(storage_stats.values())
    grand_total = total_linked + total_storage

    console.print("\n[bold]Résumé:[/bold]")
    console.print(
        f"  [green]{grand_total}[/green] film(s) associé(s) sur {initial_no_fp} manquants"
    )
    if total_linked > 0:
        console.print(f"\n  [bold]Passe 1 — symlinks ({total_linked}):[/bold]")
        for method, count in stats.items():
            if count > 0:
                console.print(f"    {method}: [green]{count}[/green]")
    if total_storage > 0:
        console.print(f"\n  [bold]Passe 2 — storage ({total_storage}):[/bold]")
        for method, count in storage_stats.items():
            if count > 0:
                console.print(f"    {method}: [green]{count}[/green]")
    console.print(f"\n  [yellow]{already}[/yellow] déjà associé(s)")
    remaining = initial_no_fp - grand_total
    if remaining > 0:
        console.print(f"  [dim]{remaining}[/dim] non résolu(s)")
    if no_target > 0:
        console.print(f"  [red]{no_target}[/red] symlink(s) sans cible valide")


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
            "--limit",
            "-l",
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

    console.print(
        f"[bold cyan]Population des tables series/episodes[/bold cyan]: {series_root}\n"
    )

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
    console.print("\n[bold]Resume:[/bold]")
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


def clean_titles() -> None:
    """Nettoie les caractères Unicode invisibles dans les titres en base."""
    from sqlmodel import select

    from src.infrastructure.persistence.database import get_session
    from src.infrastructure.persistence.models import (
        EpisodeModel,
        MovieModel,
        SeriesModel,
    )
    from src.utils.helpers import strip_invisible_chars

    session = next(get_session())
    total_cleaned = 0

    with suppress_loguru():
        for model_class, label in [
            (MovieModel, "films"),
            (SeriesModel, "séries"),
            (EpisodeModel, "épisodes"),
        ]:
            cleaned = 0
            all_items = session.exec(select(model_class)).all()
            for item in all_items:
                changed = False
                if item.title:
                    new_title = strip_invisible_chars(item.title).strip()
                    if new_title != item.title:
                        item.title = new_title
                        changed = True
                if hasattr(item, "original_title") and item.original_title:
                    new_ot = strip_invisible_chars(item.original_title).strip()
                    if new_ot != item.original_title:
                        item.original_title = new_ot
                        changed = True
                if changed:
                    session.add(item)
                    cleaned += 1

            if cleaned:
                session.commit()
            total_cleaned += cleaned
            console.print(f"  {label}: {cleaned} titres nettoyés sur {len(all_items)}")

    if total_cleaned:
        console.print(
            f"\n[green]✓[/green] {total_cleaned} titres nettoyés au total"
        )
    else:
        console.print("\n[green]✓[/green] Aucun titre à nettoyer")
    session.close()


def enrich_tech(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Nombre max de films à traiter (0 = tous)"),
    ] = 0,
) -> None:
    """Extrait les métadonnées techniques (résolution, codecs) pour les films avec fichier."""
    import json

    from sqlmodel import select

    from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor
    from src.infrastructure.persistence.database import get_session
    from src.infrastructure.persistence.models import MovieModel

    session = next(get_session())
    extractor = MediaInfoExtractor()

    stmt = (
        select(MovieModel)
        .where(MovieModel.file_path.isnot(None))
        .where(MovieModel.resolution.is_(None))
    )
    if limit > 0:
        stmt = stmt.limit(limit)
    movies = session.exec(stmt).all()

    console.print(
        f"[bold cyan]Enrichissement métadonnées techniques[/bold cyan]: "
        f"{len(movies)} films à traiter\n"
    )

    if dry_run:
        console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

    enriched = 0
    skipped = 0
    errors = 0

    with suppress_loguru():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Extraction...", total=len(movies))

            for movie in movies:
                file_path = Path(movie.file_path)

                # Résoudre si symlink
                try:
                    real_path = file_path.resolve() if file_path.is_symlink() else file_path
                except OSError:
                    real_path = file_path

                if not real_path.exists():
                    skipped += 1
                    progress.advance(task)
                    continue

                progress.update(task, description=f"[cyan]{movie.title}")

                try:
                    media_info = extractor.extract(real_path)
                except Exception:
                    errors += 1
                    progress.advance(task)
                    continue

                if not media_info:
                    skipped += 1
                    progress.advance(task)
                    continue

                if not dry_run:
                    if media_info.resolution:
                        movie.resolution = (
                            f"{media_info.resolution.width}x{media_info.resolution.height}"
                        )
                    if media_info.video_codec:
                        movie.codec_video = media_info.video_codec.name
                    if media_info.audio_codecs:
                        movie.codec_audio = media_info.audio_codecs[0].name
                    if media_info.audio_languages:
                        movie.languages_json = json.dumps(
                            [lang.code for lang in media_info.audio_languages]
                        )
                    # Taille du fichier
                    try:
                        movie.file_size_bytes = real_path.stat().st_size
                    except OSError:
                        pass
                    session.add(movie)

                    # Commit par batch de 50
                    if (enriched + 1) % 50 == 0:
                        session.commit()

                enriched += 1
                progress.advance(task)

        # Commit final
        if not dry_run and enriched > 0:
            session.commit()

    console.print("\n[bold]Résumé:[/bold]")
    console.print(f"  [green]{enriched}[/green] film(s) enrichi(s)")
    if skipped > 0:
        console.print(f"  [yellow]{skipped}[/yellow] ignoré(s) (fichier introuvable ou sans info)")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")
    session.close()


def enrich_episode_titles(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Nombre max de séries à traiter (0 = toutes)"),
    ] = 0,
) -> None:
    """Enrichit les titres d'épisodes manquants via l'API TVDB."""
    asyncio.run(_enrich_episode_titles_async(dry_run, limit))


@with_container()
async def _enrich_episode_titles_async(
    container, dry_run: bool, limit: int
) -> None:
    """Implémentation async de enrich-episode-titles."""
    from sqlalchemy import or_
    from sqlmodel import select

    from src.infrastructure.persistence.models import EpisodeModel, SeriesModel

    episode_repo = container.episode_repository()
    session = episode_repo._session
    tvdb_client = container.tvdb_client()

    # Épisodes sans titre avec tvdb_id disponible, groupés par série
    eps = session.exec(
        select(EpisodeModel, SeriesModel.tvdb_id)
        .join(SeriesModel, EpisodeModel.series_id == SeriesModel.id)
        .where(or_(EpisodeModel.title.is_(None), EpisodeModel.title == ""))
        .where(SeriesModel.tvdb_id.isnot(None))
        .order_by(EpisodeModel.series_id, EpisodeModel.season_number, EpisodeModel.episode_number)
    ).all()

    # Grouper par série
    series_groups: dict[int, list[tuple]] = {}
    for ep, tvdb_id in eps:
        series_groups.setdefault(ep.series_id, []).append((ep, tvdb_id))

    series_list = list(series_groups.items())
    if limit > 0:
        series_list = series_list[:limit]

    total_eps = sum(len(eps_list) for _, eps_list in series_list)
    console.print(
        f"[bold cyan]Enrichissement titres épisodes[/bold cyan]: "
        f"{total_eps} épisodes dans {len(series_list)} séries\n"
    )

    if dry_run:
        console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

    enriched = 0
    not_found = 0
    errors = 0

    with suppress_loguru():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Enrichissement...", total=total_eps)

            for series_id, eps_list in series_list:
                tvdb_id = eps_list[0][1]
                # Afficher le nom de la série
                series_title = session.exec(
                    select(SeriesModel.title).where(SeriesModel.id == series_id)
                ).first()
                progress.update(
                    task,
                    description=f"[cyan]{series_title or f'Série {series_id}'}",
                )

                for ep, _ in eps_list:
                    try:
                        details = await tvdb_client.get_episode_details(
                            str(tvdb_id), ep.season_number, ep.episode_number
                        )
                    except Exception:
                        errors += 1
                        progress.advance(task)
                        continue

                    if details and details.title:
                        if not dry_run:
                            ep.title = details.title
                            if details.overview:
                                ep.overview = details.overview
                            session.add(ep)
                        enriched += 1
                    else:
                        not_found += 1

                    progress.advance(task)

                # Commit par série
                if not dry_run:
                    session.commit()

    console.print("\n[bold]Résumé:[/bold]")
    console.print(f"  [green]{enriched}[/green] titre(s) enrichi(s)")
    if not_found > 0:
        console.print(f"  [yellow]{not_found}[/yellow] non trouvé(s) sur TVDB")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")

    if tvdb_client:
        await tvdb_client.close()


# --- Commande enrich-tvdb-ids ---


def enrich_tvdb_ids(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la base"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Nombre max de séries à traiter (0 = toutes)"),
    ] = 0,
) -> None:
    """Peuple les tvdb_id manquants des séries via TMDB external_ids et recherche TVDB."""
    asyncio.run(_enrich_tvdb_ids_async(dry_run, limit))


@with_container()
async def _enrich_tvdb_ids_async(
    container, dry_run: bool, limit: int
) -> None:
    """Implémentation async de enrich-tvdb-ids."""
    from difflib import SequenceMatcher

    from sqlmodel import select

    from src.infrastructure.persistence.models import SeriesModel

    series_repo = container.series_repository()
    session = series_repo._session
    tmdb_client = container.tmdb_client()
    tvdb_client = container.tvdb_client()

    # Séries sans tvdb_id
    series_list = list(
        session.exec(
            select(SeriesModel).where(SeriesModel.tvdb_id.is_(None))
        ).all()
    )
    if limit > 0:
        series_list = series_list[:limit]

    console.print(
        f"[bold cyan]Enrichissement tvdb_id[/bold cyan]: "
        f"{len(series_list)} séries sans tvdb_id\n"
    )
    if not series_list:
        console.print("[green]Aucune série à traiter.[/green]")
        return

    if dry_run:
        console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

    found_tmdb = 0
    found_tvdb = 0
    not_found = 0
    errors = 0

    with suppress_loguru():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Recherche...", total=len(series_list))

            for series in series_list:
                progress.update(
                    task,
                    description=f"[cyan]{series.title}",
                )

                tvdb_id = None
                method = ""

                # Stratégie 1 : TMDB external_ids (si tmdb_id disponible)
                if series.tmdb_id:
                    try:
                        ext_ids = await tmdb_client.get_tv_external_ids(
                            str(series.tmdb_id)
                        )
                        if ext_ids and ext_ids.get("tvdb_id"):
                            tvdb_id = int(ext_ids["tvdb_id"])
                            method = "TMDB external_ids"
                    except Exception:
                        pass

                # Stratégie 2 : Recherche TVDB par titre (FR puis original, puis racine)
                if tvdb_id is None:
                    # Titres à chercher : FR d'abord, puis original si différent
                    search_titles = [series.title]
                    if (
                        series.original_title
                        and series.original_title.lower() != series.title.lower()
                    ):
                        search_titles.append(series.original_title)
                    # Ajouter la racine (avant " - ") si le titre contient un tiret
                    for t in list(search_titles):
                        if " - " in t:
                            root = t.split(" - ")[0].strip()
                            if root not in search_titles:
                                search_titles.append(root)

                    try:
                        for search_title in search_titles:
                            if tvdb_id is not None:
                                break
                            results = await tvdb_client.search(
                                search_title, series.year
                            )
                            if not results:
                                continue

                            # Comparer contre le titre FR, l'original, et le terme de recherche
                            candidates = {series.title.lower()}
                            if series.original_title:
                                candidates.add(series.original_title.lower())
                            candidates.add(search_title.lower())

                            best = None
                            # Préparer les variantes normalisées des candidats
                            norm_candidates = {_normalize_for_match(c) for c in candidates}

                            # Match exact (case-insensitive), y compris sans année entre ()
                            for r in results:
                                if r.title:
                                    r_lower = r.title.lower()
                                    r_clean = re.sub(r"\s*\(\d{4}\)\s*$", "", r_lower)
                                    r_norm = _normalize_for_match(r.title)
                                    r_norm_clean = _normalize_for_match(r_clean)
                                    if (
                                        r_lower in candidates
                                        or r_clean in candidates
                                        or r_norm in norm_candidates
                                        or r_norm_clean in norm_candidates
                                    ):
                                        best = r
                                        break
                            # Match fuzzy ≥ 0.85 sur titres normalisés
                            if best is None:
                                for r in results:
                                    if r.title:
                                        r_norm = _normalize_for_match(r.title)
                                        for nc in norm_candidates:
                                            ratio = SequenceMatcher(
                                                None, nc, r_norm
                                            ).ratio()
                                            if ratio >= 0.85:
                                                best = r
                                                break
                                        if best:
                                            break

                            if best:
                                tvdb_id = int(best.id)
                                method = f"TVDB search \"{search_title}\" → \"{best.title}\""
                    except Exception:
                        errors += 1
                        progress.advance(task)
                        continue

                if tvdb_id:
                    if method.startswith("TMDB"):
                        found_tmdb += 1
                    else:
                        found_tvdb += 1

                    if dry_run:
                        console.print(
                            f"  [green]✓[/green] {series.title} ({series.year}) "
                            f"→ tvdb_id={tvdb_id} [dim]({method})[/dim]"
                        )
                    else:
                        series.tvdb_id = tvdb_id
                        session.add(series)
                        session.commit()
                else:
                    not_found += 1
                    if dry_run:
                        console.print(
                            f"  [yellow]✗[/yellow] {series.title} ({series.year}) "
                            f"— aucun match"
                        )

                progress.advance(task)

    console.print("\n[bold]Résumé:[/bold]")
    console.print(f"  [green]{found_tmdb}[/green] trouvé(s) via TMDB external_ids")
    console.print(f"  [green]{found_tvdb}[/green] trouvé(s) via recherche TVDB")
    console.print(f"  [bold green]{found_tmdb + found_tvdb}[/bold green] total")
    if not_found > 0:
        console.print(f"  [yellow]{not_found}[/yellow] non trouvé(s)")
    if errors > 0:
        console.print(f"  [red]{errors}[/red] erreur(s)")

    if tmdb_client:
        await tmdb_client.close()
    if tvdb_client:
        await tvdb_client.close()
