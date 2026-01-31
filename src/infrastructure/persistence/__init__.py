"""
Module de persistance SQLite pour CineOrg.

Ce module fournit l'infrastructure de stockage utilisant SQLModel (SQLAlchemy).
Il contient :

- database.py : Configuration de l'engine SQLite, session factory, initialisation
- models.py : Modeles SQLModel representant les tables de la base de donnees
- hash_service.py : Service de calcul de hash XXHash par echantillons
- repositories/ : Implementations SQLModel des ports repository

Les modeles ici sont des adapters de persistance, distincts des entites de domaine
(dataclass dans core/entities/). La conversion entre les deux se fait dans les
repositories.

Usage:
    from src.infrastructure.persistence import init_db, get_session
    from src.infrastructure.persistence import MovieModel, SeriesModel
    from src.infrastructure.persistence import compute_file_hash
    from src.infrastructure.persistence.repositories import SQLModelMovieRepository

    init_db()  # Cree les tables si necessaire
    with next(get_session()) as session:
        movie = MovieModel(title="Inception", year=2010)
        session.add(movie)
        session.commit()
"""

from src.infrastructure.persistence.database import (
    get_engine,
    get_session,
    init_db,
)
from src.infrastructure.persistence.hash_service import compute_file_hash
from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    PendingValidationModel,
    SeriesModel,
    TrashModel,
    VideoFileModel,
)
from src.infrastructure.persistence.repositories import (
    SQLModelMovieRepository,
    SQLModelSeriesRepository,
    SQLModelEpisodeRepository,
    SQLModelVideoFileRepository,
    SQLModelPendingValidationRepository,
)

__all__ = [
    # Database
    "get_engine",
    "get_session",
    "init_db",
    # Hash service
    "compute_file_hash",
    # Models
    "MovieModel",
    "SeriesModel",
    "EpisodeModel",
    "VideoFileModel",
    "PendingValidationModel",
    "TrashModel",
    # Repositories
    "SQLModelMovieRepository",
    "SQLModelSeriesRepository",
    "SQLModelEpisodeRepository",
    "SQLModelVideoFileRepository",
    "SQLModelPendingValidationRepository",
]
