"""
Container d'injection de dependances via dependency-injector.

Fournit une gestion centralisee des dependances pour les interfaces CLI et Web.
Les repositories et clients API sont ajoutes dans les phases ulterieures.
"""

from dependency_injector import containers, providers

from .adapters.file_system import FileSystemAdapter
from .adapters.parsing.guessit_parser import GuessitFilenameParser
from .adapters.parsing.mediainfo_extractor import MediaInfoExtractor
from .config import Settings
from .services.scanner import ScannerService


class Container(containers.DeclarativeContainer):
    """Container DI de l'application.

    Fournit l'injection de dependances pour les interfaces CLI et Web.
    Les repositories et clients API sont ajoutes dans les phases ulterieures.

    Utilisation :
        container = Container()
        scanner = container.scanner_service()
    """

    # Le wiring est fait explicitement dans main.py pour eviter les problemes d'import
    # Modules a wirer :
    # - src.main (point d'entree CLI)
    # - src.adapters.cli.commands (ajoute plus tard)
    # - src.adapters.web.routes.* (ajoute plus tard)

    # Configuration - singleton charge une seule fois
    config = providers.Singleton(Settings)

    # Adapters - implementations concretes des ports
    file_system = providers.Singleton(FileSystemAdapter)
    filename_parser = providers.Singleton(GuessitFilenameParser)
    media_info_extractor = providers.Singleton(MediaInfoExtractor)

    # Services
    scanner_service = providers.Factory(
        ScannerService,
        file_system=file_system,
        filename_parser=filename_parser,
        media_info_extractor=media_info_extractor,
        settings=config,
    )

    # Repositories - a implementer en Phase 4
    # video_repository = providers.Singleton(...)
    # movie_repository = providers.Singleton(...)

    # Clients API - a implementer en Phase 3
    # tmdb_client = providers.Factory(...)
    # tvdb_client = providers.Factory(...)
