"""
Container d'injection de dependances via dependency-injector.

Fournit une gestion centralisee des dependances pour les interfaces CLI et Web.
Inclut les repositories SQLModel et les services de persistance.
"""

from dependency_injector import containers, providers

from .adapters.api.cache import APICache
from .adapters.api.tmdb_client import TMDBClient
from .adapters.api.tvdb_client import TVDBClient
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
from .infrastructure.persistence.hash_service import compute_file_hash
from .services.importer import ImporterService
from .services.matcher import MatcherService
from .services.scanner import ScannerService
from .services.renamer import RenamerService
from .services.organizer import OrganizerService
from .services.quality_scorer import QualityScorerService
from .services.transferer import TransfererService
from .services.validation import ValidationService


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

    # Cache API - Singleton pour partage entre clients
    api_cache = providers.Singleton(
        APICache,
        cache_dir=".cache/api",
    )

    # Clients API - Singleton avec api_key depuis config
    # Si api_key est None/vide, le client sera cree mais ValidationService
    # gere ce cas en verifiant client._api_key avant utilisation
    tmdb_client = providers.Singleton(
        TMDBClient,
        api_key=config.provided.tmdb_api_key,
        cache=api_cache,
    )

    tvdb_client = providers.Singleton(
        TVDBClient,
        api_key=config.provided.tvdb_api_key,
        cache=api_cache,
    )

    # Service de scoring (stateless - Singleton)
    matcher_service = providers.Singleton(MatcherService)

    # Service de validation - Factory car depend de repositories (sessions fraiches)
    validation_service = providers.Factory(
        ValidationService,
        pending_repo=pending_validation_repository,
        matcher=matcher_service,
        tmdb_client=tmdb_client,
        tvdb_client=tvdb_client,
    )

    # Service d'import de videotheque - Factory car depend de repositories
    # Utiliser: container.importer_service(dry_run=True/False)
    importer_service = providers.Factory(
        ImporterService,
        file_system=file_system,
        filename_parser=filename_parser,
        media_info_extractor=media_info_extractor,
        video_file_repo=video_file_repository,
        pending_repo=pending_validation_repository,
        compute_hash_fn=compute_file_hash,
    )
