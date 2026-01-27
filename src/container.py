"""
Container d'injection de dependances via dependency-injector.

Fournit une gestion centralisee des dependances pour les interfaces CLI et Web.
Inclut les repositories SQLModel et les services de persistance.
"""

from dependency_injector import containers, providers

from .adapters.file_system import FileSystemAdapter
from .adapters.parsing.guessit_parser import GuessitFilenameParser
from .adapters.parsing.mediainfo_extractor import MediaInfoExtractor
from .config import Settings
from .infrastructure.persistence.database import init_db, get_session
from .infrastructure.persistence.repositories import (
    SQLModelMovieRepository,
    SQLModelSeriesRepository,
    SQLModelEpisodeRepository,
    SQLModelVideoFileRepository,
    SQLModelPendingValidationRepository,
)
from .services.scanner import ScannerService
from .services.renamer import RenamerService
from .services.organizer import OrganizerService
from .services.quality_scorer import QualityScorerService
from .services.transferer import TransfererService


class Container(containers.DeclarativeContainer):
    """Container DI de l'application.

    Fournit l'injection de dependances pour les interfaces CLI et Web.
    Inclut les repositories SQLModel pour la persistance.

    Utilisation :
        container = Container()
        container.database.init()  # Initialise la DB une fois
        scanner = container.scanner_service()
        movie_repo = container.movie_repository()
    """

    # Le wiring est fait explicitement dans main.py pour eviter les problemes d'import
    # Modules a wirer :
    # - src.main (point d'entree CLI)
    # - src.adapters.cli.commands (ajoute plus tard)
    # - src.adapters.web.routes.* (ajoute plus tard)

    # Configuration - singleton charge une seule fois
    config = providers.Singleton(Settings)

    # Database - Resource pour initialisation unique
    database = providers.Resource(init_db)

    # Session factory - nouvelle session a chaque appel
    session = providers.Factory(lambda: next(get_session()))

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

    # Repositories - Factory pour nouvelle instance avec session fraiche
    movie_repository = providers.Factory(
        SQLModelMovieRepository,
        session=session,
    )
    series_repository = providers.Factory(
        SQLModelSeriesRepository,
        session=session,
    )
    episode_repository = providers.Factory(
        SQLModelEpisodeRepository,
        session=session,
    )
    video_file_repository = providers.Factory(
        SQLModelVideoFileRepository,
        session=session,
    )
    pending_validation_repository = providers.Factory(
        SQLModelPendingValidationRepository,
        session=session,
    )

    # Services de renommage et organisation (stateless - Singletons)
    renamer_service = providers.Singleton(RenamerService)
    organizer_service = providers.Singleton(OrganizerService)
    quality_scorer_service = providers.Singleton(QualityScorerService)

    # Service de transfert - Factory car depend des paths de configuration
    # Note: storage_dir et video_dir sont injectes via config.paths_storage/paths_video
    # Utiliser: container.transferer_service(storage_dir=Path(...), video_dir=Path(...))
    transferer_service = providers.Factory(
        TransfererService,
        file_system=file_system,
        symlink_manager=file_system,  # FileSystemAdapter implemente les deux interfaces
    )

    # Clients API - a implementer en Phase 3
    # tmdb_client = providers.Factory(...)
    # tvdb_client = providers.Factory(...)
