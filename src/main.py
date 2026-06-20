"""
Point d'entrée CLI de CineOrg.

Initialise le container DI, configure le logging et fournit les commandes CLI.
"""

from typing import Annotated

import typer
from loguru import logger

from .adapters.cli.commands import (
    check,
    cleanup,
    consolidate,
    enrich,
    enrich_collections,
    enrich_imdb_ids,
    enrich_movies_credits,
    enrich_ratings,
    enrich_series,
    fix_bad_links,
    fix_symlinks,
    imdb_app,
    migrate_nas_app,
    migrate_series,
    fix_series_symlinks,
    check_duplicates,
    clean_titles,
    enrich_episode_titles,
    enrich_tech,
    enrich_tvdb_ids,
    import_library,
    link_movie_parts,
    link_movies,
    pending,
    populate_movies,
    populate_series,
    process,
    purge_hardlinks,
    rename_canonical,
    reconcile,
    regroup,
    repair_links,
    validate_app,
)
import logging as _logging

from .config import Settings
from .container import Container
from .logging_config import configure_logging
from .version import get_version


class _LoguruInterceptHandler(_logging.Handler):
    """Redirige les logs stdlib (uvicorn) vers loguru."""

    def emit(self, record: _logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage()
        )

app = typer.Typer(
    name="cineorg",
    help="Application de gestion de vidéothèque",
)
container = Container()

# Etat global pour les options de verbosite
state = {"verbose": 0, "quiet": False}


@app.callback()
def main_callback(
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose", "-v", count=True, help="Augmenter la verbosite (-v, -vv, -vvv)"
        ),
    ] = 0,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Mode silencieux (erreurs uniquement)"),
    ] = False,
) -> None:
    """CineOrg - Gestion de videotheque personnelle."""
    if quiet:
        state["quiet"] = True
    else:
        state["verbose"] = verbose


# Monter les commandes depuis commands.py
app.command()(process)
app.command()(pending)
# Note: "import" est un mot reserve Python, donc on utilise name= explicitement
app.command(name="import")(import_library)

# Commandes de maintenance
app.command()(enrich)
app.command(name="populate-movies")(populate_movies)
app.command(name="populate-series")(populate_series)
app.command(name="link-movies")(link_movies)
app.command(name="link-movie-parts")(link_movie_parts)
app.command(name="enrich-ratings")(enrich_ratings)
app.command(name="enrich-imdb-ids")(enrich_imdb_ids)
app.command(name="enrich-series")(enrich_series)
app.command(name="enrich-movies-credits")(enrich_movies_credits)
app.command(name="enrich-collections")(enrich_collections)
app.command(name="repair-links")(repair_links)
app.command()(consolidate)
app.command()(check)
app.command()(cleanup)
app.command()(regroup)
app.command(name="fix-symlinks")(fix_symlinks)
app.command(name="fix-bad-links")(fix_bad_links)
app.command(name="clean-titles")(clean_titles)
app.command(name="enrich-tech")(enrich_tech)
app.command(name="enrich-episode-titles")(enrich_episode_titles)
app.command(name="enrich-tvdb-ids")(enrich_tvdb_ids)
app.command()(reconcile)
app.command(name="migrate-series")(migrate_series)
app.command(name="fix-series-symlinks")(fix_series_symlinks)
app.command(name="check-duplicates")(check_duplicates)
app.command(name="purge-hardlinks")(purge_hardlinks)
app.command(name="rename-canonical")(rename_canonical)

# Monter validate_app comme sous-commande
app.add_typer(validate_app, name="validate")

# Monter imdb_app comme sous-commande
app.add_typer(imdb_app, name="imdb")

# Monter migrate_nas_app comme sous-commande (plan / apply / status)
app.add_typer(migrate_nas_app, name="migrate-nas")


def get_config() -> Settings:
    """Récupère les paramètres de l'application depuis le container DI."""
    return container.config()


@app.command()
def info() -> None:
    """Affiche la configuration actuelle."""
    config = get_config()
    logger.info("Configuration CineOrg")
    typer.echo(f"Téléchargements : {config.downloads_dir}")
    typer.echo(f"Stockage : {config.storage_dir}")
    typer.echo(f"Vidéo : {config.video_dir}")
    typer.echo(f"Base de données : {config.database_url}")
    typer.echo(f"API TMDB : {'activée' if config.tmdb_enabled else 'désactivée'}")
    typer.echo(f"API TVDB : {'activée' if config.tvdb_enabled else 'désactivée'}")
    typer.echo(f"Niveau de log : {config.log_level}")


@app.command()
def version() -> None:
    """Affiche les informations de version."""
    typer.echo(f"CineOrg v{get_version()}")


@app.command()
def scan() -> None:
    """Scanne les repertoires de telechargements."""
    scanner = container.scanner_service()

    count = 0
    for result in scanner.scan_downloads():
        typer.echo(f"Found: {result.video_file.filename}")
        typer.echo(f"  Type: {result.detected_type.value}")
        typer.echo(f"  Title: {result.parsed_info.title}")
        if result.parsed_info.year:
            typer.echo(f"  Year: {result.parsed_info.year}")
        if result.parsed_info.season is not None:
            ep_range = f"E{result.parsed_info.episode:02d}"
            if result.parsed_info.episode_end:
                ep_range += f"-E{result.parsed_info.episode_end:02d}"
            typer.echo(f"  Season/Episode: S{result.parsed_info.season:02d}{ep_range}")
        if result.media_info:
            if result.media_info.resolution:
                typer.echo(f"  Resolution: {result.media_info.resolution.label}")
            if result.media_info.video_codec:
                typer.echo(f"  Video Codec: {result.media_info.video_codec.name}")
            if result.media_info.duration_seconds:
                minutes = result.media_info.duration_seconds // 60
                typer.echo(f"  Duration: {minutes} min")
        if result.corrected_location:
            typer.echo("  WARNING: File in wrong directory!")
        typer.echo("")
        count += 1

    typer.echo(f"Total: {count} files found")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Adresse d'écoute")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Port d'écoute")] = 8000,
    reload: Annotated[bool, typer.Option(help="Rechargement automatique")] = False,
    workers: Annotated[int, typer.Option(help="Nombre de workers uvicorn")] = 1,
    access_log: Annotated[bool, typer.Option(help="Activer les logs d'accès HTTP")] = True,
) -> None:
    """Lance le serveur web CineOrg."""
    import uvicorn

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "loguru": {
                "()": _LoguruInterceptHandler,
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["loguru"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["loguru"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["loguru"], "level": "INFO", "propagate": False},
        },
    }

    typer.echo(f"Démarrage du serveur sur {host}:{port} ({workers} worker(s))")

    import os
    import signal
    import subprocess

    def _kill_port_holders(target_port: int) -> None:
        """Tue les process qui occupent encore le port."""
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{target_port}"],
                capture_output=True, text=True, timeout=5,
            )
            pids = result.stdout.strip().split()
            my_pid = str(os.getpid())
            for pid in pids:
                if pid and pid != my_pid:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    original_sigint = signal.getsignal(signal.SIGINT)

    def _shutdown(signum: int, frame: object) -> None:
        # Restaurer le handler par défaut pour éviter la boucle
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        _kill_port_holders(port)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        uvicorn.run(
            "src.web.app:app",
            host=host,
            port=port,
            reload=reload,
            workers=workers,
            access_log=access_log,
            log_config=log_config,
        )
    except SystemExit:
        _kill_port_holders(port)


def main() -> None:
    """Point d'entrée de l'application."""
    # Charge la configuration et configure le logging
    settings = container.config()
    configure_logging(
        log_level=settings.log_level,
        log_file=settings.log_file,
        rotation_size=settings.log_rotation_size,
        retention_count=settings.log_retention_count,
    )

    # Initialise la base de données (crée les tables si nécessaire)
    container.database.init()

    logger.info("Démarrage de CineOrg", version="0.1.0")

    # Lance la CLI
    app()


if __name__ == "__main__":
    main()
