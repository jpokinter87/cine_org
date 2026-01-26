"""
Dependency Injection container using dependency-injector.

Provides centralized dependency management for both CLI and Web interfaces.
Repositories and API clients are added in later phases.
"""

from dependency_injector import containers, providers

from .config import Settings


class Container(containers.DeclarativeContainer):
    """Application DI container.

    Provides dependency injection for both CLI and Web interfaces.
    Repositories and API clients are added in later phases.

    Usage:
        container = Container()
        container.wire(modules=[__name__])
        settings = container.config()
    """

    # Wiring is done explicitly in main.py to avoid import issues
    # Modules to wire:
    # - src.main (CLI entry point)
    # - src.adapters.cli.commands (added later)
    # - src.adapters.web.routes.* (added later)

    # Configuration - singleton loaded once
    config = providers.Singleton(Settings)

    # Repositories - to be implemented in Phase 4
    # video_repository = providers.Singleton(...)
    # movie_repository = providers.Singleton(...)

    # API Clients - to be implemented in Phase 3
    # tmdb_client = providers.Factory(...)
    # tvdb_client = providers.Factory(...)

    # Services - to be implemented in later phases
    # scanner = providers.Factory(...)
    # matcher = providers.Factory(...)
