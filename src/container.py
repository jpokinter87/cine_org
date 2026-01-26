"""
Container d'injection de dépendances via dependency-injector.

Fournit une gestion centralisée des dépendances pour les interfaces CLI et Web.
Les repositories et clients API sont ajoutés dans les phases ultérieures.
"""

from dependency_injector import containers, providers

from .config import Settings


class Container(containers.DeclarativeContainer):
    """Container DI de l'application.

    Fournit l'injection de dépendances pour les interfaces CLI et Web.
    Les repositories et clients API sont ajoutés dans les phases ultérieures.

    Utilisation :
        container = Container()
        container.wire(modules=[__name__])
        settings = container.config()
    """

    # Le wiring est fait explicitement dans main.py pour éviter les problèmes d'import
    # Modules à wirer :
    # - src.main (point d'entrée CLI)
    # - src.adapters.cli.commands (ajouté plus tard)
    # - src.adapters.web.routes.* (ajouté plus tard)

    # Configuration - singleton chargé une seule fois
    config = providers.Singleton(Settings)

    # Repositories - à implémenter en Phase 4
    # video_repository = providers.Singleton(...)
    # movie_repository = providers.Singleton(...)

    # Clients API - à implémenter en Phase 3
    # tmdb_client = providers.Factory(...)
    # tvdb_client = providers.Factory(...)

    # Services - à implémenter dans les phases ultérieures
    # scanner = providers.Factory(...)
    # matcher = providers.Factory(...)
