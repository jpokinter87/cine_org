"""Commande CLI check-duplicates : detection des doublons dans la videotheque."""

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from loguru import logger as loguru_logger
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from sqlalchemy import text

from src.adapters.cli.validation import console
from src.container import Container
from src.core.value_objects.media_info import (
    AudioCodec,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.services.quality_scorer import calculate_quality_score

# Chemin par defaut de la whitelist
_WHITELIST_PATH = Path("config/duplicates_whitelist.json")


def _load_whitelist(path: Path) -> dict:
    """Charge la whitelist depuis le fichier JSON."""
    if not path.exists():
        return {"whitelist": [], "notes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "whitelist" not in data:
            data["whitelist"] = []
        if "notes" not in data:
            data["notes"] = {}
        return data
    except (json.JSONDecodeError, OSError):
        return {"whitelist": [], "notes": {}}


def _save_whitelist(path: Path, data: dict) -> None:
    """Sauvegarde la whitelist dans le fichier JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_media_info(
    resolution_str: Optional[str],
    codec_video: Optional[str],
    codec_audio: Optional[str],
) -> Optional[MediaInfo]:
    """Reconstruit un MediaInfo depuis les champs string de MovieModel."""
    resolution = None
    video_codec = None
    audio_codecs: tuple[AudioCodec, ...] = ()

    if resolution_str and "x" in resolution_str:
        try:
            w, h = resolution_str.split("x")
            resolution = Resolution(width=int(w), height=int(h))
        except (ValueError, TypeError):
            pass

    if codec_video:
        video_codec = VideoCodec(name=codec_video)

    if codec_audio:
        audio_codecs = (AudioCodec(name=codec_audio),)

    if resolution is None and video_codec is None:
        return None

    return MediaInfo(
        resolution=resolution,
        video_codec=video_codec,
        audio_codecs=audio_codecs,
    )


def _format_size(size_bytes: Optional[int]) -> str:
    """Formate une taille en octets en format lisible."""
    if not size_bytes:
        return "?"
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    return f"{size_bytes / 1_048_576:.0f} Mo"


def _format_resolution(resolution_str: Optional[str]) -> str:
    """Convertit '1920x1080' en '1080p' etc."""
    if not resolution_str or "x" not in resolution_str:
        return "?"
    try:
        _, h = resolution_str.split("x")
        height = int(h)
        if height >= 2160:
            return "4K"
        elif height >= 1080:
            return "1080p"
        elif height >= 720:
            return "720p"
        else:
            return "SD"
    except (ValueError, TypeError):
        return "?"


def _format_languages(languages_json: Optional[str]) -> str:
    """Formate les langues depuis le JSON."""
    if not languages_json:
        return "?"
    try:
        langs = json.loads(languages_json)
        return ", ".join(lang.upper() if len(lang) <= 3 else lang for lang in langs)
    except (json.JSONDecodeError, TypeError):
        return "?"


def _short_path(file_path: Optional[str]) -> str:
    """Extrait le nom du fichier depuis le chemin complet."""
    if not file_path:
        return "?"
    return Path(file_path).name


def check_duplicates(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Afficher le detail des scores par critere"),
    ] = False,
    whitelist_add: Annotated[
        Optional[int],
        typer.Option("--whitelist-add", help="Ajouter un tmdb_id a la whitelist"),
    ] = None,
    whitelist_remove: Annotated[
        Optional[int],
        typer.Option("--whitelist-remove", help="Retirer un tmdb_id de la whitelist"),
    ] = None,
) -> None:
    """Detecte les films en double dans la videotheque (meme tmdb_id)."""
    # Gestion whitelist add/remove
    if whitelist_add is not None or whitelist_remove is not None:
        wl = _load_whitelist(_WHITELIST_PATH)
        if whitelist_add is not None:
            if whitelist_add not in wl["whitelist"]:
                wl["whitelist"].append(whitelist_add)
                _save_whitelist(_WHITELIST_PATH, wl)
                console.print(
                    f"[green]tmdb_id {whitelist_add} ajoute a la whitelist[/green]"
                )
            else:
                console.print(
                    f"[yellow]tmdb_id {whitelist_add} deja dans la whitelist[/yellow]"
                )
        if whitelist_remove is not None:
            if whitelist_remove in wl["whitelist"]:
                wl["whitelist"].remove(whitelist_remove)
                wl["notes"].pop(str(whitelist_remove), None)
                _save_whitelist(_WHITELIST_PATH, wl)
                console.print(
                    f"[green]tmdb_id {whitelist_remove} retire de la whitelist[/green]"
                )
            else:
                console.print(
                    f"[yellow]tmdb_id {whitelist_remove} pas dans la whitelist[/yellow]"
                )
        if whitelist_add is not None or whitelist_remove is not None:
            # Si c'est juste une operation whitelist sans analyse, on s'arrete
            return

    container = Container()
    container.database.init()

    loguru_logger.disable("src")

    console.print("[bold cyan]Detection des doublons[/bold cyan]\n")

    # Charger la whitelist
    whitelist_data = _load_whitelist(_WHITELIST_PATH)
    whitelisted_ids = set(whitelist_data.get("whitelist", []))
    whitelist_notes = whitelist_data.get("notes", {})

    # Detecter les doublons via SQL
    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        scan_task = progress.add_task("[cyan]Analyse des doublons...", total=None)

        rows = session.execute(
            text("""
                SELECT tmdb_id, COUNT(*) as cnt,
                       GROUP_CONCAT(id) as ids
                FROM movies
                WHERE tmdb_id IS NOT NULL AND file_path IS NOT NULL
                GROUP BY tmdb_id
                HAVING COUNT(*) > 1
                ORDER BY cnt DESC
            """)
        ).fetchall()

        progress.update(scan_task, description="[green]Analyse terminee")

    if not rows:
        console.print("[green]Aucun doublon detecte.[/green]")
        loguru_logger.enable("src")
        return

    # Separer doublons et whitelistes
    duplicate_groups = []
    whitelisted_groups = []

    for row in rows:
        tmdb_id = row[0]
        count = row[1]
        movie_ids = [int(mid) for mid in row[2].split(",")]

        # Charger les details de chaque film
        movies_data = []
        for mid in movie_ids:
            movie_row = session.execute(
                text("""
                    SELECT id, title, year, file_path, resolution, codec_video,
                           codec_audio, languages_json, file_size_bytes, duration_seconds,
                           poster_path
                    FROM movies WHERE id = :mid
                """),
                {"mid": mid},
            ).fetchone()

            if movie_row:
                mi = _build_media_info(movie_row[4], movie_row[5], movie_row[6])
                score = calculate_quality_score(
                    mi,
                    movie_row[8] or 0,
                    movie_row[9],
                )
                movies_data.append(
                    {
                        "id": movie_row[0],
                        "title": movie_row[1],
                        "year": movie_row[2],
                        "file_path": movie_row[3],
                        "resolution": movie_row[4],
                        "codec_video": movie_row[5],
                        "codec_audio": movie_row[6],
                        "languages": movie_row[7],
                        "size_bytes": movie_row[8],
                        "duration": movie_row[9],
                        "score": score,
                    }
                )

        if not movies_data:
            continue

        group = {
            "tmdb_id": tmdb_id,
            "count": count,
            "title": movies_data[0]["title"],
            "year": movies_data[0]["year"],
            "movies": sorted(movies_data, key=lambda m: m["score"].total, reverse=True),
        }

        if tmdb_id in whitelisted_ids:
            group["note"] = whitelist_notes.get(str(tmdb_id), "")
            whitelisted_groups.append(group)
        else:
            duplicate_groups.append(group)

    # Affichage des doublons a traiter
    total_recoverable = 0

    if duplicate_groups:
        console.print(
            f"[bold red]{len(duplicate_groups)} groupe(s) de doublons detecte(s)[/bold red]\n"
        )

        for group in duplicate_groups:
            title = f"{group['title']} ({group['year'] or '?'})"
            table = Table(
                title=f"[bold]{title}[/bold] — tmdb_id {group['tmdb_id']}",
                show_header=True,
                title_style="bold cyan",
            )
            table.add_column("", width=3)  # indicateur best
            table.add_column("Fichier", style="white", max_width=60)
            table.add_column("Resolution", justify="center")
            table.add_column("Codec", justify="center")
            table.add_column("Audio", justify="center")
            table.add_column("Langues", justify="center")
            table.add_column("Taille", justify="right")
            table.add_column("Score", justify="right", style="bold")

            if verbose:
                table.add_column("Detail", style="dim")

            best_score = group["movies"][0]["score"].total

            for movie in group["movies"]:
                is_best = movie["score"].total == best_score
                indicator = "[green]★[/green]" if is_best else " "
                score_style = "bold green" if is_best else "dim"
                score_str = f"[{score_style}]{movie['score'].total:.1f}[/{score_style}]"

                row = [
                    indicator,
                    _short_path(movie["file_path"]),
                    _format_resolution(movie["resolution"]),
                    movie["codec_video"] or "?",
                    movie["codec_audio"] or "?",
                    _format_languages(movie["languages"]),
                    _format_size(movie["size_bytes"]),
                    score_str,
                ]

                if verbose:
                    s = movie["score"]
                    detail = (
                        f"res={s.resolution_score:.0f} "
                        f"vc={s.video_codec_score:.0f} "
                        f"br={s.bitrate_score:.0f} "
                        f"au={s.audio_score:.0f} "
                        f"sz={s.size_efficiency:.0f}"
                    )
                    row.append(detail)

                table.add_row(*row)

                if not is_best and movie["size_bytes"]:
                    total_recoverable += movie["size_bytes"]

            console.print(table)
            console.print()
    else:
        console.print("[green]Aucun doublon a traiter.[/green]\n")

    # Affichage des whitelistes
    if whitelisted_groups:
        console.print(
            f"[bold yellow]{len(whitelisted_groups)} groupe(s) accepte(s) (whitelist)[/bold yellow]\n"
        )
        for group in whitelisted_groups:
            title = f"{group['title']} ({group['year'] or '?'})"
            note = f" — {group['note']}" if group.get("note") else ""
            copies = ", ".join(
                f"{_format_resolution(m['resolution'])} {m['codec_video'] or '?'}"
                for m in group["movies"]
            )
            console.print(f"  [yellow]•[/yellow] {title}{note} [{copies}]")
        console.print()

    # Resume
    total_files = sum(g["count"] for g in duplicate_groups)
    summary_parts = [
        f"[bold]{len(duplicate_groups)}[/bold] groupe(s) de doublons",
        f"[bold]{total_files}[/bold] fichiers concernes",
    ]
    if total_recoverable > 0:
        summary_parts.append(
            f"[bold]{_format_size(total_recoverable)}[/bold] recuperable(s)"
        )
    if whitelisted_groups:
        summary_parts.append(
            f"[yellow]{len(whitelisted_groups)}[/yellow] accepte(s)"
        )

    console.print(
        Panel(
            " | ".join(summary_parts),
            title="Resume",
            style="cyan",
        )
    )

    if duplicate_groups:
        console.print(
            "\n[dim]Pour accepter un doublon : "
            "check-duplicates --whitelist-add TMDB_ID[/dim]"
        )

    loguru_logger.enable("src")
