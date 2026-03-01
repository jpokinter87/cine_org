"""
Commande CLI fix-series-symlinks : verifie et repare les symlinks series.

Scanne les repertoires de symlinks series (TV, Animation, Mangas, etc.)
et detecte les non-conformites : absence de sous-repertoire Saison,
titre d'episode manquant, specifications techniques manquantes.

Reconstruit les symlinks non conformes en utilisant les donnees DB
et les services renamer/organizer existants.
"""

import json
import re
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table
from rich.text import Text
from sqlalchemy import text

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.container import Container
from src.core.entities.media import Episode, Series
from src.core.value_objects.media_info import MediaInfo, Resolution, VideoCodec
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.services.renamer import generate_series_filename

# Pattern pour detecter un repertoire "Saison XX"
_SAISON_RE = re.compile(r"^Saison \d{2}$")


# Mapping codec guessit → nomenclature standard (identique a MediaInfoExtractor)
_GUESSIT_CODEC_MAP = {
    "h.264": "x264",
    "h264": "x264",
    "x264": "x264",
    "h.265": "x265",
    "h265": "x265",
    "x265": "x265",
    "hevc": "x265",
    "av1": "AV1",
    "vp9": "VP9",
    "mpeg-4 visual": "MPEG-4",
    "xvid": "XviD",
    "divx": "DivX",
}

# Mapping resolution guessit → dimensions (largeur, hauteur)
_GUESSIT_RESOLUTION_MAP = {
    "2160p": (3840, 2160),
    "4k": (3840, 2160),
    "1080p": (1920, 1080),
    "1080i": (1920, 1080),
    "720p": (1280, 720),
    "576p": (720, 576),
    "480p": (720, 480),
}


def _build_media_info_from_guessit(parsed: ParsedFilename) -> Optional[MediaInfo]:
    """Construit un MediaInfo depuis les donnees guessit (ParsedFilename)."""
    resolution = None
    if parsed.resolution:
        dims = _GUESSIT_RESOLUTION_MAP.get(parsed.resolution.lower())
        if dims:
            resolution = Resolution(width=dims[0], height=dims[1])

    video_codec = None
    if parsed.video_codec:
        codec_name = _GUESSIT_CODEC_MAP.get(
            parsed.video_codec.lower(), parsed.video_codec
        )
        video_codec = VideoCodec(name=codec_name)

    if not resolution and not video_codec:
        return None

    return MediaInfo(resolution=resolution, video_codec=video_codec)


def _check_saison_dir(symlink_path: Path) -> bool:
    """Verifie que le symlink est dans un repertoire Saison XX."""
    return bool(_SAISON_RE.match(symlink_path.parent.name))


def _normalize_for_compare(text: str) -> str:
    """Normalise un texte pour comparaison (retire ponctuation, normalise espaces)."""
    text = text.lower()
    # Decomposer les ligatures courantes
    text = text.replace("œ", "oe").replace("æ", "ae")
    # Unifier slash et tiret (ex: "1/3" vs "1-3")
    text = text.replace("/", "-")
    # Retirer les caractères spéciaux (guillemets, tirets de remplacement, etc.)
    text = re.sub(r'["\'\-–—.…?!:;,()]+', " ", text)
    # Normaliser les espaces multiples
    return " ".join(text.split())


def _check_episode_title(symlink_name: str, episode_title: Optional[str]) -> bool:
    """Verifie que le nom du symlink contient le titre d'episode."""
    if not episode_title:
        return True  # Pas de titre en DB, rien a verifier
    # Normaliser pour la comparaison (ignorer ponctuation et casse)
    normalized_name = _normalize_for_compare(symlink_name)
    normalized_title = _normalize_for_compare(episode_title)
    return normalized_title in normalized_name


def _check_tech_specs(symlink_name: str) -> dict[str, bool]:
    """Verifie la presence des specifications techniques dans le nom."""
    name_upper = symlink_name.upper()
    has_resolution = bool(re.search(r"\d{3,4}P", name_upper)) or " SD" in name_upper
    has_codec = any(
        c in name_upper for c in ("HEVC", "H.264", "H264", "X264", "X265", "AV1", "VP9", "MPEG-4", "XVID", "DIVX")
    )
    has_language = any(
        lang in name_upper
        for lang in ("MULTI", "FRENCH", "VOSTFR", " FR ", " EN ", " DE ")
    )
    return {
        "resolution": has_resolution,
        "codec": has_codec,
        "language": has_language,
    }


def _generate_expected_name(
    series: Series,
    episode: Episode,
    media_info: Optional[MediaInfo],
    fallback_lang: Optional[str],
    extension: str,
    fallback_subtitle_lang: Optional[str] = None,
) -> str:
    """Genere le nom attendu du symlink via le renamer standard."""
    return generate_series_filename(
        series=series,
        episode=episode,
        media_info=media_info,
        extension=extension,
        fallback_language=fallback_lang,
        fallback_subtitle_language=fallback_subtitle_lang,
    )


def fix_series_symlinks(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Afficher le plan sans executer"),
    ] = True,
    series_filter: Annotated[
        Optional[str],
        typer.Option("--series", help="Filtrer par nom de serie (partiel)"),
    ] = None,
    type_filter: Annotated[
        Optional[str],
        typer.Option("--type", help="Filtrer par type (TV, Animation, Mangas)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Afficher le detail des differences"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", help="Limiter le nombre de details affiches (mode verbose)"
        ),
    ] = 20,
) -> None:
    """Verifie et repare les symlinks series non conformes."""
    container = Container()
    container.database.init()
    config = container.config()
    video_dir = config.video_dir

    with suppress_loguru():
        console.print("\n[bold cyan]Verification des symlinks series[/bold cyan]\n")

        from src.infrastructure.persistence.database import get_session

        session = next(get_session())

        # Scanner tous les episodes avec file_path
        query = (
            "SELECT e.id, e.series_id, e.season_number, e.episode_number, e.title, "
            "e.codec_video, e.codec_audio, e.resolution, e.languages_json, e.file_path, "
            "s.title as series_title, s.year as series_year, s.genres_json "
            "FROM episodes e "
            "JOIN series s ON s.id = e.series_id "
            "WHERE e.file_path IS NOT NULL"
        )
        params = {}
        if series_filter:
            query += " AND s.title LIKE :sf"
            params["sf"] = f"%{series_filter}%"

        all_episodes = session.execute(text(query), params).fetchall()

        # Construire l'index des symlinks existants (une seule passe)
        console.print("[dim]Construction de l'index des symlinks...[/dim]")
        symlink_index = _build_symlink_index(video_dir)
        console.print(f"[dim]{len(symlink_index)} symlinks indexes.[/dim]\n")

        # Analyser les non-conformites
        from rich.progress import Progress

        issues: list[dict] = []

        with Progress(console=console) as progress:
            scan_task = progress.add_task(
                "Analyse des episodes...", total=len(all_episodes)
            )

            for row in all_episodes:
                series = Series(
                    id=str(row.series_id),
                    title=row.series_title,
                    year=row.series_year,
                    genres=tuple(json.loads(row.genres_json)) if row.genres_json else (),
                )
                episode = Episode(
                    id=str(row.id),
                    series_id=str(row.series_id),
                    season_number=row.season_number,
                    episode_number=row.episode_number,
                    title=row.title,
                    codec_video=row.codec_video,
                    codec_audio=row.codec_audio,
                    resolution=row.resolution,
                    languages=tuple(json.loads(row.languages_json))
                    if row.languages_json
                    else (),
                )

                storage_path = Path(row.file_path)
                if not storage_path.exists():
                    progress.advance(scan_task)
                    continue

                # Determiner le type de serie
                series_type = "TV"
                genres_lower = [g.lower() for g in series.genres]
                if "anime" in genres_lower:
                    series_type = "Mangas"
                elif "animation" in genres_lower:
                    series_type = "Animation"
                elif "documentaire" in genres_lower:
                    series_type = "Series documentaires"

                if type_filter and series_type.lower() != type_filter.lower():
                    progress.advance(scan_task)
                    continue

                # Chercher le symlink actuel pour cet episode (via l'index)
                actual_symlink = _find_existing_symlink_from_index(
                    symlink_index, storage_path
                )

                if actual_symlink is None:
                    issues.append(
                        {
                            "series": f"{series.title} ({series.year or '?'})",
                            "type": series_type,
                            "episode": f"S{row.season_number:02d}E{row.episode_number:02d}",
                            "problems": ["symlink manquant"],
                            "details": [],
                            "storage_path": str(storage_path),
                            "actual_symlink": None,
                            "series_obj": series,
                            "episode_obj": episode,
                            "row": row,
                        }
                    )
                    progress.advance(scan_task)
                    continue

                # Verifier la conformite structurelle
                problems = []
                details = []

                # 1. Sous-repertoire Saison
                if not _check_saison_dir(actual_symlink):
                    problems.append("pas de Saison")
                    details.append(
                        f"parent: {actual_symlink.parent.name} (attendu: Saison {row.season_number:02d})"
                    )

                # 2. Titre d'episode
                if row.title and not _check_episode_title(actual_symlink.name, row.title):
                    problems.append("titre episode absent")
                    details.append(f"titre DB: {row.title}")

                # 3. Specifications techniques
                tech = _check_tech_specs(actual_symlink.name)
                missing_tech = [k for k, v in tech.items() if not v]
                if missing_tech:
                    problems.append(f"specs manquantes ({', '.join(missing_tech)})")

                if problems:
                    issues.append(
                        {
                            "series": f"{series.title} ({series.year or '?'})",
                            "type": series_type,
                            "episode": f"S{row.season_number:02d}E{row.episode_number:02d}",
                            "problems": problems,
                            "details": details,
                            "storage_path": str(storage_path),
                            "actual_symlink": str(actual_symlink),
                            "series_obj": series,
                            "episode_obj": episode,
                            "row": row,
                        }
                    )

                progress.advance(scan_task)

        # Afficher le rapport
        if not issues:
            console.print("[green]Tous les symlinks sont conformes.[/green]")
            return

        # Grouper par serie pour l'affichage
        by_series: dict[str, list[dict]] = {}
        for issue in issues:
            key = issue["series"]
            by_series.setdefault(key, []).append(issue)

        table = Table(
            title=f"Symlinks non conformes ({len(issues)} episodes)",
            show_header=True,
        )
        table.add_column("Serie", style="cyan")
        table.add_column("Type", style="dim")
        table.add_column("Episodes", justify="right", style="yellow")
        table.add_column("Problemes", style="red")
        for series_name, series_issues in sorted(by_series.items()):
            problem_set: set[str] = set()
            for si in series_issues:
                problem_set.update(si["problems"])
            table.add_row(
                Text(series_name),
                series_issues[0]["type"],
                str(len(series_issues)),
                " / ".join(sorted(problem_set)),
            )
        console.print(table)

        if verbose:
            console.print(
                f"\n[bold]Details des {min(limit, len(issues))} premieres "
                f"non-conformites :[/bold]\n"
            )
            for issue in issues[:limit]:
                console.print(
                    f"[cyan]{issue['series']}[/cyan] {issue['episode']} "
                    f"[dim]({', '.join(issue['problems'])})[/dim]"
                )
                if issue["actual_symlink"]:
                    console.print(f"  [dim]symlink:[/dim] {issue['actual_symlink']}")
                for detail in issue["details"]:
                    console.print(f"  [yellow]{detail}[/yellow]")
                console.print()

        if dry_run:
            console.print(
                f"\n[yellow]Mode dry-run : {len(issues)} symlinks a corriger.[/yellow]"
            )
            console.print(
                "[dim]Relancer avec --no-dry-run pour executer les corrections.[/dim]"
            )
            return

        # Execution : reconstruire les symlinks non conformes
        from rich.prompt import Confirm

        if not Confirm.ask(
            f"\n[bold]Corriger {len(issues)} symlinks ?[/bold]", default=False
        ):
            console.print("[yellow]Correction annulee.[/yellow]")
            return

        import asyncio

        fixed, errors, enriched_titles = asyncio.run(
            _fix_all_issues(issues, video_dir, verbose)
        )

        console.print(f"\n[bold green]{fixed} symlinks corriges.[/bold green]")
        if enriched_titles:
            console.print(
                f"[green]{enriched_titles} titres d'episodes enrichis via TVDB.[/green]"
            )
        if errors:
            console.print(f"[red]{errors} erreurs.[/red]")


def _extract_tech_from_storage(
    storage_path: Path,
    parser: GuessitFilenameParser,
    extractor: object,
) -> tuple[Optional[MediaInfo], Optional[str], Optional[str]]:
    """
    Extrait les infos techniques du fichier storage (pipeline identique au workflow).

    Strategie identique au workflow normal :
    1. mediainfo sur le fichier physique → MediaInfo (source primaire)
    2. guessit sur le nom de fichier → fallback_language, fallback_subtitle_language

    Si mediainfo echoue (fichier NAS inaccessible), fallback sur guessit
    pour construire un MediaInfo minimal.

    Returns:
        Tuple (media_info, fallback_language, fallback_subtitle_language)
    """
    # 1. guessit pour la langue (toujours, c'est rapide)
    parsed = parser.parse(storage_path.name, type_hint=MediaType.SERIES)
    fallback_language = parsed.language
    fallback_subtitle_language = parsed.subtitle_language

    # 2. mediainfo sur le fichier physique (source primaire, comme le workflow)
    media_info = None
    try:
        media_info = extractor.extract(storage_path)
    except Exception:
        pass

    # 3. Si mediainfo a echoue, fallback sur guessit pour les specs
    if not media_info:
        media_info = _build_media_info_from_guessit(parsed)

    return media_info, fallback_language, fallback_subtitle_language


async def _fix_all_issues(
    issues: list[dict],
    video_dir: Path,
    verbose: bool,
) -> tuple[int, int, int]:
    """
    Corrige tous les symlinks non conformes en utilisant le pipeline complet.

    Pipeline identique au workflow : mediainfo + guessit + TVDB pour titres.

    Returns:
        Tuple (fixed, errors, enriched_titles)
    """
    from rich.progress import Progress

    from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor

    # Initialiser les services (une seule instance chacun)
    guessit_parser = GuessitFilenameParser()
    mediainfo_extractor = MediaInfoExtractor()

    # Initialiser TVDB pour les titres d'episodes manquants
    tvdb_client = None
    try:
        container = Container()
        tvdb_client = container.tvdb_client()
        if not getattr(tvdb_client, "_api_key", None):
            tvdb_client = None
    except Exception:
        pass

    # Session DB pour mettre a jour les titres enrichis
    from src.infrastructure.persistence.database import get_session

    db_session = next(get_session())

    fixed = 0
    errors = 0
    enriched_titles = 0

    with Progress(console=console) as progress:
        task = progress.add_task("Correction des symlinks...", total=len(issues))

        for issue in issues:
            try:
                row = issue["row"]
                series_obj = issue["series_obj"]
                episode_obj = issue["episode_obj"]
                storage_path = Path(issue["storage_path"])

                # Pipeline complet : mediainfo (primaire) + guessit (langue)
                media_info, fallback_lang, fallback_sub_lang = (
                    _extract_tech_from_storage(
                        storage_path, guessit_parser, mediainfo_extractor
                    )
                )

                # Enrichir le titre d'episode si manquant (TVDB)
                if not episode_obj.title and tvdb_client and hasattr(row, "series_id"):
                    ep_title = await _fetch_episode_title(
                        tvdb_client,
                        db_session,
                        row.series_id,
                        row.season_number,
                        row.episode_number,
                        row.id,
                    )
                    if ep_title:
                        episode_obj = Episode(
                            id=episode_obj.id,
                            series_id=episode_obj.series_id,
                            season_number=episode_obj.season_number,
                            episode_number=episode_obj.episode_number,
                            title=ep_title,
                            codec_video=episode_obj.codec_video,
                            codec_audio=episode_obj.codec_audio,
                            resolution=episode_obj.resolution,
                            languages=episode_obj.languages,
                        )
                        enriched_titles += 1

                # Generer le nom attendu via le renamer standard
                expected_name = _generate_expected_name(
                    series_obj,
                    episode_obj,
                    media_info,
                    fallback_lang,
                    storage_path.suffix,
                    fallback_sub_lang,
                )

                # Determiner le bon repertoire
                actual_path = (
                    Path(issue["actual_symlink"]) if issue["actual_symlink"] else None
                )
                expected_dir = _compute_expected_dir(
                    actual_path, series_obj, row.season_number, video_dir
                )
                expected_path = expected_dir / expected_name

                # Supprimer l'ancien symlink
                if actual_path and actual_path.is_symlink():
                    actual_path.unlink()

                # Creer le nouveau symlink
                expected_path.parent.mkdir(parents=True, exist_ok=True)
                if not expected_path.exists():
                    expected_path.symlink_to(storage_path)
                    fixed += 1

                # Nettoyer les repertoires vides
                if actual_path and actual_path.parent != expected_path.parent:
                    _cleanup_empty_dirs(actual_path.parent, video_dir)

            except Exception as e:
                errors += 1
                if verbose:
                    console.print(f"  [red]Erreur {issue['episode']}:[/red] {e}")

            progress.advance(task)

    # Committer les titres enrichis
    if enriched_titles:
        db_session.commit()

    return fixed, errors, enriched_titles


async def _fetch_episode_title(
    tvdb_client,
    db_session,
    series_id: int,
    season_number: int,
    episode_number: int,
    episode_db_id: int,
) -> Optional[str]:
    """
    Recupere le titre d'episode depuis TVDB et le sauvegarde en DB.

    Utilise le tvdb_id de la serie pour appeler l'API.
    """
    # Recuperer le tvdb_id de la serie
    result = db_session.execute(
        text("SELECT tvdb_id FROM series WHERE id = :sid"),
        {"sid": series_id},
    )
    row = result.fetchone()
    if not row or not row.tvdb_id:
        return None

    try:
        ep_details = await tvdb_client.get_episode_details(
            str(row.tvdb_id), season_number, episode_number
        )
        if ep_details and ep_details.title:
            # Sauvegarder en DB
            db_session.execute(
                text("UPDATE episodes SET title = :title WHERE id = :eid"),
                {"title": ep_details.title, "eid": episode_db_id},
            )
            return ep_details.title
    except Exception:
        pass

    return None


def _compute_expected_dir(
    actual_path: Optional[Path],
    series: Series,
    season_number: int,
    video_dir: Path,
) -> Path:
    """
    Calcule le repertoire attendu pour le symlink.

    Remonte l'arborescence depuis le symlink actuel pour trouver :
    1. Un repertoire Saison correctement formate → le reutiliser
    2. Un repertoire Saison mal formate (Saison 1) → corriger le format
    3. Le repertoire de la serie → ajouter Saison XX
    """
    season_folder = f"Saison {season_number:02d}"

    if not actual_path:
        return video_dir / season_folder

    # Remonter l'arborescence pour trouver un repere
    current = actual_path.parent
    while current != video_dir and current != current.parent:
        name = current.name
        # Repertoire Saison correctement formate (Saison 01, Saison 02)
        if _SAISON_RE.match(name):
            return current
        # Repertoire Saison mal formate (Saison 1, Saison 2, Saison 10)
        if re.match(r"^Saison \d+$", name):
            return current.parent / season_folder
        current = current.parent

    # Pas de Saison trouve — chercher le repertoire de la serie
    # Collecter tous les candidats et prendre le plus haut (le vrai dossier serie)
    series_dir_candidate = None
    current = actual_path.parent
    while current != video_dir and current != current.parent:
        if series.title.lower() in current.name.lower():
            series_dir_candidate = current
        current = current.parent

    if series_dir_candidate:
        return series_dir_candidate / season_folder

    # Dernier fallback : parent du symlink + Saison
    return actual_path.parent / season_folder


def _build_symlink_index(video_dir: Path) -> dict[Path, Path]:
    """Construit un index {storage_path_resolved: symlink_path} pour toutes les series."""
    index: dict[Path, Path] = {}
    scan_dirs = []
    series_root = video_dir / "Series"
    if series_root.exists():
        scan_dirs.append(series_root)
    doc_root = video_dir / "Documentaires"
    if doc_root.exists():
        scan_dirs.append(doc_root)

    for scan_dir in scan_dirs:
        for link in scan_dir.rglob("*"):
            if not link.is_symlink():
                continue
            try:
                resolved = link.resolve()
                index[resolved] = link
            except OSError:
                continue

    return index


def _find_existing_symlink_from_index(
    index: dict[Path, Path],
    storage_path: Path,
) -> Optional[Path]:
    """Cherche un symlink existant dans l'index pre-construit."""
    return index.get(storage_path.resolve())


def _cleanup_empty_dirs(directory: Path, stop_at: Path) -> None:
    """Supprime les repertoires vides en remontant jusqu'a stop_at."""
    current = directory
    while current != stop_at and current.exists():
        try:
            if any(current.iterdir()):
                break  # Pas vide
            current.rmdir()
            current = current.parent
        except OSError:
            break
