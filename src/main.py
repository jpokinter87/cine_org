"""
CineOrg CLI entry point.

Initializes the DI container, configures logging, and provides CLI commands.
"""

import typer
from loguru import logger

from .config import Settings
from .container import Container
from .logging_config import configure_logging

app = typer.Typer(
    name="cineorg",
    help="Video library management application",
)
container = Container()


def get_config() -> Settings:
    """Get the application settings from the DI container."""
    return container.config()


@app.command()
def info() -> None:
    """Display current configuration."""
    config = get_config()
    logger.info("CineOrg configuration")
    typer.echo(f"Downloads: {config.downloads_dir}")
    typer.echo(f"Storage: {config.storage_dir}")
    typer.echo(f"Video: {config.video_dir}")
    typer.echo(f"Database: {config.database_url}")
    typer.echo(f"TMDB API: {'enabled' if config.tmdb_enabled else 'disabled'}")
    typer.echo(f"TVDB API: {'enabled' if config.tvdb_enabled else 'disabled'}")
    typer.echo(f"Log level: {config.log_level}")


@app.command()
def version() -> None:
    """Display version information."""
    typer.echo("CineOrg v0.1.0")


def main() -> None:
    """Application entry point."""
    # Load configuration and setup logging
    settings = container.config()
    configure_logging(
        log_level=settings.log_level,
        log_file=settings.log_file,
        rotation_size=settings.log_rotation_size,
        retention_count=settings.log_retention_count,
    )

    logger.info("CineOrg starting", version="0.1.0")

    # Run CLI
    app()


if __name__ == "__main__":
    main()
