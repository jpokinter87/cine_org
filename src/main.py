"""
Point d'entrée CLI de CineOrg.

Initialise le container DI, configure le logging et fournit les commandes CLI.
"""

import typer
from loguru import logger

from .config import Settings
from .container import Container
from .logging_config import configure_logging

app = typer.Typer(
    name="cineorg",
    help="Application de gestion de vidéothèque",
)
container = Container()


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
    typer.echo("CineOrg v0.1.0")


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

    logger.info("Démarrage de CineOrg", version="0.1.0")

    # Lance la CLI
    app()


if __name__ == "__main__":
    main()
