"""
Module de persistance SQLite pour CineOrg.

Ce module fournit l'infrastructure de stockage utilisant SQLModel (SQLAlchemy).
Il contient :

- database.py : Configuration de l'engine SQLite, session factory, initialisation
- models.py : Modeles SQLModel representant les tables de la base de donnees

Les modeles ici sont des adapters de persistance, distincts des entites de domaine
(dataclass dans core/entities/). La conversion entre les deux se fait dans les
repositories.

Usage:
    from src.infrastructure.persistence import init_db, get_session
    from src.infrastructure.persistence import MovieModel, SeriesModel

    init_db()  # Cree les tables si necessaire
    with next(get_session()) as session:
        movie = MovieModel(title="Inception", year=2010)
        session.add(movie)
        session.commit()
"""

from src.infrastructure.persistence.database import (
    DATA_DIR,
    DATABASE_URL,
    engine,
    get_session,
    init_db,
)

# Les modeles seront importes apres leur creation dans models.py
# Pour eviter les erreurs d'import circulaire, on les importe conditionnellement
try:
    from src.infrastructure.persistence.models import (
        EpisodeModel,
        MovieModel,
        PendingValidationModel,
        SeriesModel,
        TrashModel,
        VideoFileModel,
    )

    __all__ = [
        "DATA_DIR",
        "DATABASE_URL",
        "engine",
        "get_session",
        "init_db",
        "MovieModel",
        "SeriesModel",
        "EpisodeModel",
        "VideoFileModel",
        "PendingValidationModel",
        "TrashModel",
    ]
except ImportError:
    # models.py pas encore cree
    __all__ = [
        "DATA_DIR",
        "DATABASE_URL",
        "engine",
        "get_session",
        "init_db",
    ]
