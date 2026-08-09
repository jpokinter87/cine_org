"""
Commande CLI de réconciliation symlinks/storage.

Résout les symlinks cassés via les métadonnées DB et met à jour les symlinks
épisodes avec les titres TVDB enrichis.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console


def reconcile(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier (affiche le rapport)"),
    ] = False,
    update_titles: Annotated[
        bool,
        typer.Option(
            "--update-titles",
            help="Renomme les symlinks épisodes avec les titres TVDB enrichis",
        ),
    ] = False,
) -> None:
    """
    Réconcilie les symlinks cassés avec les fichiers dans storage.

    Recherche les fichiers physiques via les métadonnées DB quand
    l'arborescence video/ et storage/ ont divergé.
    """
    asyncio.run(_reconcile_async(dry_run, update_titles))


@with_container()
async def _reconcile_async(container, dry_run: bool, update_titles: bool) -> None:
    """Implémentation async de la commande reconcile."""
    from sqlmodel import select

    from src.infrastructure.persistence.database import get_session
    from src.infrastructure.persistence.models import (
        EpisodeModel,
        MovieModel,
        SeriesModel,
    )

    config = container.config()
    storage_dir = Path(config.storage_dir)
    video_dir = Path(config.video_dir)

    # Obtenir une session DB pour la recherche métadonnées
    session = next(get_session())

    with suppress_loguru():
        if dry_run:
            console.print("[yellow]Mode dry-run — aucune modification[/yellow]\n")

        # --- Phase 0 : Réconciliation DB ↔ fichiers storage ---
        console.print("[bold]Phase 0 : Réconciliation DB ↔ fichiers storage[/bold]\n")
        _reconcile_db_file_paths(
            session,
            select,
            storage_dir,
            dry_run,
            MovieModel,
            EpisodeModel,
            SeriesModel,
        )

        # --- Phase 1 : Réconciliation des symlinks cassés ---
        console.print("\n[bold]Phase 1 : Réconciliation des symlinks cassés[/bold]\n")

        repair_service = container.repair_service(
            storage_dir=storage_dir,
            video_dir=video_dir,
            db_session=session,
        )

        # Trouver les symlinks cassés
        broken_links = repair_service.find_broken_symlinks()
        console.print(f"  Symlinks cassés trouvés : [bold]{len(broken_links)}[/bold]")

        if not broken_links:
            console.print("  [green]Aucun symlink cassé — rien à réconcilier[/green]\n")
        else:
            reconciled_metadata = 0
            reconciled_search = 0
            unresolved = 0
            actions: list[dict] = []
            remaining: list[Path] = []

            # Passe 1 : recherche rapide par métadonnées DB
            console.print("  Passe 1 : recherche par métadonnées DB...")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                transient=True,
            ) as progress:
                task = progress.add_task("Métadonnées DB...", total=len(broken_links))

                for link in broken_links:
                    progress.advance(task)
                    candidates = repair_service._find_by_metadata(link)

                    if candidates and candidates[0][1] >= 85:
                        best_target, best_score = candidates[0]
                        reconciled_metadata += 1
                        actions.append(
                            {
                                "link": link,
                                "target": best_target,
                                "score": best_score,
                                "method": "metadata",
                            }
                        )
                    else:
                        remaining.append(link)

            console.print(
                f"    Résolus : [green]{reconciled_metadata}[/green], "
                f"restants : {len(remaining)}"
            )

            # Passe 2 : recherche par nom de fichier via index rapide
            if remaining:
                console.print("  Passe 2 : recherche par index rapide...")
                reconciled_search, still_remaining = _fast_index_search(
                    remaining,
                    storage_dir,
                    actions,
                )
                unresolved = len(still_remaining)
                console.print(
                    f"    Résolus : [green]{reconciled_search}[/green], "
                    f"non résolus : [red]{unresolved}[/red]"
                )

            # Appliquer les corrections
            if actions and not dry_run:
                for a in actions:
                    _update_db_file_path(
                        session,
                        select,
                        a["link"],
                        a["target"],
                        MovieModel,
                        EpisodeModel,
                        SeriesModel,
                    )
                    repair_service.repair_symlink(a["link"], a["target"])

            # Rapport
            console.print()
            table = Table(title="Rapport de réconciliation")
            table.add_column("Métrique", style="cyan")
            table.add_column("Valeur", style="bold")
            table.add_row("Symlinks cassés", str(len(broken_links)))
            table.add_row("Réconciliés (métadonnées DB)", str(reconciled_metadata))
            table.add_row("Réconciliés (recherche storage)", str(reconciled_search))
            table.add_row(
                "Total réconciliés",
                f"[green]{reconciled_metadata + reconciled_search}[/green]",
            )
            table.add_row("Non résolus", f"[red]{unresolved}[/red]")
            console.print(table)

            # Détail des actions
            if actions and len(actions) <= 50:
                console.print()
                detail_table = Table(title="Détail des réconciliations")
                detail_table.add_column("Symlink", style="dim", max_width=50)
                detail_table.add_column("Cible", style="green", max_width=50)
                detail_table.add_column("Score", justify="right")
                detail_table.add_column("Méthode")
                for a in actions:
                    detail_table.add_row(
                        a["link"].name,
                        a["target"].name,
                        f"{a['score']:.0f}%",
                        a["method"],
                    )
                console.print(detail_table)

        # --- Phase 2 : Mise à jour des titres épisodes ---
        if update_titles:
            console.print(
                "\n[bold]Phase 2 : Mise à jour symlinks épisodes (titres TVDB)[/bold]\n"
            )
            _update_episode_titles(
                session,
                select,
                video_dir,
                dry_run,
                SeriesModel,
                EpisodeModel,
            )

        if not dry_run:
            session.commit()

        console.print("\n[green]Réconciliation terminée.[/green]")


def _reconcile_db_file_paths(
    session,
    select,
    storage_dir: Path,
    dry_run: bool,
    MovieModel,
    EpisodeModel,
    SeriesModel,
) -> None:
    """
    Réconcilie les file_path en DB avec les fichiers physiques dans storage.

    Traite :
    - Films avec file_path NULL → cherche le fichier dans storage/Films/
    - Films avec file_path périmé (fichier n'existe plus) → idem
    - Épisodes avec file_path NULL ou périmé → cherche dans storage/Séries/
    """
    from difflib import SequenceMatcher

    from src.adapters.file_system import VIDEO_EXTENSIONS
    from src.services.repair.filename_analyzer import extract_clean_title

    # --- Index rapide des fichiers storage ---
    console.print("  Construction de l'index storage...")
    # Index par titre normalisé → [(chemin, année_depuis_chemin)]
    films_by_name: dict[str, list[Path]] = {}
    series_by_name: dict[str, list[Path]] = {}

    for f in storage_dir.rglob("*"):
        try:
            if f.is_symlink() or f.is_dir():
                continue
            if f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            clean = extract_clean_title(f.name)
            path_str = str(f).lower()
            if "/films/" in path_str:
                if clean not in films_by_name:
                    films_by_name[clean] = []
                films_by_name[clean].append(f)
            elif "/séries/" in path_str or "/series/" in path_str:
                if clean not in series_by_name:
                    series_by_name[clean] = []
                series_by_name[clean].append(f)
        except (PermissionError, OSError):
            continue

    console.print(
        f"  Index : {sum(len(v) for v in films_by_name.values())} films, "
        f"{sum(len(v) for v in series_by_name.values())} épisodes"
    )

    # --- Réconciliation des films ---
    movies_null = session.exec(
        select(MovieModel).where(MovieModel.file_path.is_(None))
    ).all()
    movies_stale = [
        m
        for m in session.exec(
            select(MovieModel).where(MovieModel.file_path.isnot(None))
        ).all()
        if not Path(m.file_path).exists()
    ]
    movies_to_fix = movies_null + movies_stale

    console.print(
        f"  Films à réconcilier : {len(movies_to_fix)} "
        f"({len(movies_null)} sans file_path, {len(movies_stale)} périmés)"
    )

    matched_count = 0
    for movie in movies_to_fix:
        # Chercher par titre normalisé
        clean_title = extract_clean_title(
            f"{movie.title} ({movie.year})" if movie.year else movie.title
        )
        candidates = films_by_name.get(clean_title, [])

        # Essayer aussi avec le titre original
        if not candidates and movie.original_title:
            clean_original = extract_clean_title(
                f"{movie.original_title} ({movie.year})"
                if movie.year
                else movie.original_title
            )
            candidates = films_by_name.get(clean_original, [])

        # Essayer le titre seul (sans année) si pas trouvé
        if not candidates:
            clean_short = extract_clean_title(movie.title)
            candidates = films_by_name.get(clean_short, [])

        # Fuzzy sur les clés proches (limité aux clés qui commencent pareil)
        if not candidates:
            prefix = clean_title[:4] if len(clean_title) >= 4 else clean_title
            for key, paths in films_by_name.items():
                if key.startswith(prefix):
                    ratio = SequenceMatcher(None, clean_title, key).ratio()
                    if ratio >= 0.85:
                        candidates = paths
                        break

        if candidates:
            best = candidates[0]
            if dry_run:
                if matched_count < 20:  # Limiter l'affichage
                    console.print(
                        f"    [dim]{movie.title} ({movie.year})[/dim] → "
                        f"[green]{best.name}[/green]"
                    )
            else:
                movie.file_path = str(best)
                session.add(movie)
            matched_count += 1

    console.print(
        f"  Films réconciliés : [green]{matched_count}[/green] / {len(movies_to_fix)}"
    )

    # --- Réconciliation des épisodes ---
    from src.services.repair.filename_analyzer import extract_series_info

    episodes_null = session.exec(
        select(EpisodeModel).where(EpisodeModel.file_path.is_(None))
    ).all()
    episodes_stale = [
        e
        for e in session.exec(
            select(EpisodeModel).where(EpisodeModel.file_path.isnot(None))
        ).all()
        if not Path(e.file_path).exists()
    ]
    episodes_to_fix = episodes_null + episodes_stale

    console.print(
        f"  Épisodes à réconcilier : {len(episodes_to_fix)} "
        f"({len(episodes_null)} sans file_path, {len(episodes_stale)} périmés)"
    )

    ep_matched = 0
    # Pré-charger les séries pour lookup rapide
    all_series = {s.id: s for s in session.exec(select(SeriesModel)).all()}

    for episode in episodes_to_fix:
        series = all_series.get(episode.series_id)
        if not series:
            continue

        # Construire le pattern attendu : SxxExx
        ep_code = f"s{episode.season_number:02d}e{episode.episode_number:02d}"

        # Chercher dans l'index par titre série
        clean_series = extract_clean_title(series.title)
        candidates = series_by_name.get(clean_series, [])

        # Filtrer les candidats par saison/épisode
        for cand in candidates:
            _, cand_season, cand_ep, _ = extract_series_info(cand.name)
            if (
                cand_season == episode.season_number
                and cand_ep == episode.episode_number
            ):
                if dry_run:
                    if ep_matched < 10:
                        console.print(
                            f"    [dim]{series.title} {ep_code.upper()}[/dim] → "
                            f"[green]{cand.name}[/green]"
                        )
                else:
                    episode.file_path = str(cand)
                    session.add(episode)
                ep_matched += 1
                break

    console.print(
        f"  Épisodes réconciliés : [green]{ep_matched}[/green] / {len(episodes_to_fix)}"
    )

    if not dry_run:
        session.commit()
        console.print("  [green]Modifications enregistrées[/green]")


def _fast_index_search(
    remaining: list[Path],
    storage_dir: Path,
    actions: list[dict],
) -> tuple[int, list[Path]]:
    """
    Recherche rapide par dictionnaire de noms de fichiers.

    Construit un index {nom_fichier → chemin} et {titre_normalisé → [chemins]}
    une seule fois, puis fait des lookups O(1) pour chaque symlink.

    Returns:
        Tuple (nombre résolus, liste des non-résolus)
    """
    from difflib import SequenceMatcher

    from src.adapters.file_system import VIDEO_EXTENSIONS
    from src.services.repair.filename_analyzer import extract_clean_title

    # Construire l'index en une seule passe
    index_by_name: dict[str, Path] = {}  # nom_exact → chemin
    index_by_clean: dict[str, list[Path]] = {}  # titre_normalisé → [chemins]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("Construction de l'index rapide...", total=None)

        for f in storage_dir.rglob("*"):
            try:
                if f.is_symlink() or f.is_dir():
                    continue
                if f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                # Index par nom exact
                index_by_name[f.name] = f
                # Index par titre normalisé
                clean = extract_clean_title(f.name)
                if clean not in index_by_clean:
                    index_by_clean[clean] = []
                index_by_clean[clean].append(f)
            except (PermissionError, OSError):
                continue

    console.print(
        f"    Index rapide : {len(index_by_name)} fichiers, "
        f"{len(index_by_clean)} titres uniques"
    )

    # Recherche par lookup
    resolved = 0
    still_remaining: list[Path] = []

    for link in remaining:
        link_name = link.name

        # 1. Match exact par nom de fichier (ex: même fichier déplacé)
        try:
            original_target = link.readlink()
            original_name = original_target.name
        except OSError:
            original_name = link_name

        # Chercher le nom du symlink ou de la cible originale
        found = index_by_name.get(link_name) or index_by_name.get(original_name)
        if found:
            resolved += 1
            actions.append(
                {
                    "link": link,
                    "target": found,
                    "score": 100.0,
                    "method": "index-exact",
                }
            )
            continue

        # 2. Match par titre normalisé
        clean_link = extract_clean_title(link_name)
        candidates = index_by_clean.get(clean_link, [])

        if candidates:
            # Prendre le premier candidat (le plus probable)
            resolved += 1
            actions.append(
                {
                    "link": link,
                    "target": candidates[0],
                    "score": 95.0,
                    "method": "index-title",
                }
            )
            continue

        # 3. Match fuzzy parmi les titres proches (limité)
        best_score = 0.0
        best_path = None
        for clean_key, paths in index_by_clean.items():
            ratio = SequenceMatcher(None, clean_link, clean_key).ratio()
            if ratio > best_score:
                best_score = ratio
                best_path = paths[0]

        if best_score >= 0.85 and best_path:
            resolved += 1
            actions.append(
                {
                    "link": link,
                    "target": best_path,
                    "score": best_score * 100,
                    "method": "index-fuzzy",
                }
            )
            continue

        still_remaining.append(link)

    return resolved, still_remaining


def _update_db_file_path(
    session,
    select,
    link: Path,
    new_target: Path,
    MovieModel,
    EpisodeModel,
    SeriesModel,
) -> None:
    """Met à jour le file_path dans la DB quand un fichier est retrouvé."""
    from src.services.repair.filename_analyzer import extract_series_info

    link_name = link.name
    _, season, episode_num, _ = extract_series_info(link_name)
    is_episode = season is not None and episode_num is not None
    new_path_str = str(new_target)

    if is_episode and "séries" in str(link).lower():
        # Chercher l'épisode correspondant et mettre à jour
        episodes = session.exec(
            select(EpisodeModel).where(
                EpisodeModel.season_number == season,
                EpisodeModel.episode_number == episode_num,
            )
        ).all()
        for ep in episodes:
            # Vérifier que le file_path actuel est périmé
            if not ep.file_path or not Path(ep.file_path).exists():
                ep.file_path = new_path_str
                session.add(ep)
                break
    else:
        # Chercher le film correspondant et mettre à jour
        movies = session.exec(
            select(MovieModel).where(
                MovieModel.file_path.is_(None) | ~MovieModel.file_path.contains("/")
            )
        ).all()
        # Cibler le film dont l'ancien file_path correspond le mieux
        for movie in movies:
            if movie.file_path and Path(movie.file_path).name == new_target.name:
                movie.file_path = new_path_str
                session.add(movie)
                break
            elif not movie.file_path:
                # Comparer par titre
                from src.services.repair.filename_analyzer import extract_clean_title

                clean_link = extract_clean_title(link_name)
                if movie.title and movie.title.lower().strip() in clean_link:
                    movie.file_path = new_path_str
                    session.add(movie)
                    break


def _update_episode_titles(
    session,
    select,
    video_dir: Path,
    dry_run: bool,
    SeriesModel,
    EpisodeModel,
) -> None:
    """Renomme les symlinks épisodes avec les titres TVDB enrichis."""
    from src.services.repair.filename_analyzer import extract_series_info

    # Supporter les deux variantes (avant et après migration)
    series_dir = video_dir / "Series"
    if not series_dir.exists():
        series_dir = video_dir / "Séries"
    if not series_dir.exists():
        console.print("  [yellow]Répertoire Series/ introuvable[/yellow]")
        return

    renamed_count = 0
    skipped_count = 0

    # Scanner tous les symlinks dans Series/
    symlinks = [f for f in series_dir.rglob("*") if f.is_symlink() and f.is_file()]

    console.print(f"  Symlinks épisodes trouvés : {len(symlinks)}")

    for symlink in symlinks:
        title, season, episode_num, year = extract_series_info(symlink.name)
        if season is None or episode_num is None:
            continue

        # Chercher la série et l'épisode en DB
        series_list = session.exec(
            select(SeriesModel).where(SeriesModel.title.contains(title))
        ).all()

        if not series_list:
            continue

        for series in series_list:
            episode = session.exec(
                select(EpisodeModel).where(
                    EpisodeModel.series_id == series.id,
                    EpisodeModel.season_number == season,
                    EpisodeModel.episode_number == episode_num,
                )
            ).first()

            if not episode or not episode.title:
                continue

            # Vérifier si le titre TVDB est déjà dans le nom du symlink
            from src.services.renamer import sanitize_for_filesystem

            expected_title = sanitize_for_filesystem(episode.title)

            if expected_title.lower() in symlink.stem.lower():
                skipped_count += 1
                break

            # Construire le nouveau nom avec le titre TVDB
            # Format : {Série} ({Année}) - SxxExx - {Titre TVDB} - {specs}.{ext}
            from src.core.entities.media import (
                Episode as EpisodeEntity,
                Series as SeriesEntity,
            )

            series_entity = SeriesEntity(
                title=series.title,
                year=series.year,
            )
            episode_entity = EpisodeEntity(
                season_number=episode.season_number,
                episode_number=episode.episode_number,
                episode_end=episode.episode_end,
                title=episode.title,
            )

            # Extraire les specs techniques du nom actuel
            media_info = _extract_media_info_from_filename(symlink.name)

            from src.services.renamer import generate_series_filename

            new_name = generate_series_filename(
                series_entity,
                episode_entity,
                media_info,
                symlink.suffix,
            )

            if new_name == symlink.name:
                skipped_count += 1
                break

            new_path = symlink.parent / new_name
            if dry_run:
                console.print(f"  [dim]{symlink.name}[/dim]")
                console.print(f"    → [green]{new_name}[/green]")
                renamed_count += 1
            else:
                try:
                    symlink.rename(new_path)
                    renamed_count += 1
                except OSError as e:
                    console.print(f"  [red]Erreur renommage {symlink.name}: {e}[/red]")
            break

    console.print(f"\n  Renommés : [green]{renamed_count}[/green]")
    console.print(f"  Déjà à jour : {skipped_count}")


def _extract_media_info_from_filename(filename: str):
    """Extrait les informations techniques d'un nom de fichier via guessit."""
    from src.core.value_objects.media_info import (
        AudioCodec,
        Language,
        MediaInfo,
        Resolution,
        VideoCodec,
    )

    try:
        from guessit import guessit

        result = guessit(filename)

        # Résolution
        resolution = None
        screen_size = str(result.get("screen_size", ""))
        res_mapping = {
            "2160p": Resolution(width=3840, height=2160),
            "1080p": Resolution(width=1920, height=1080),
            "720p": Resolution(width=1280, height=720),
            "480p": Resolution(width=720, height=480),
        }
        resolution = res_mapping.get(screen_size)

        # Codec vidéo
        video_codec = None
        vc = str(result.get("video_codec", ""))
        if vc:
            # Normaliser le nom du codec
            vc_name = vc.replace("H.265", "HEVC").replace("H.264", "x264")
            video_codec = VideoCodec(name=vc_name)

        # Codec audio
        audio_codecs = ()
        ac = result.get("audio_codec", "")
        if ac:
            audio_codecs = (AudioCodec(name=str(ac)),)

        # Langues
        audio_languages = ()
        language = result.get("language")
        if language:
            if hasattr(language, "alpha2"):
                audio_languages = (Language(code=language.alpha2, name=""),)
            elif isinstance(language, list) and language:
                audio_languages = tuple(
                    Language(
                        code=lang.alpha2 if hasattr(lang, "alpha2") else str(lang),
                        name="",
                    )
                    for lang in language
                )

        return MediaInfo(
            resolution=resolution,
            video_codec=video_codec,
            audio_codecs=audio_codecs,
            audio_languages=audio_languages,
        )
    except Exception:
        return None
