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
