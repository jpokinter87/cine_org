"""
Configuration de la base de donnees SQLite pour CineOrg.

Ce module fournit :
- Engine SQLite avec configuration optimisee pour multi-thread
- Session factory avec context manager
- Fonction d'initialisation des tables

La base de donnees est creee dans data/cineorg.db au premier appel de init_db().
"""

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import Session, SQLModel, create_engine

# Repertoire de donnees - cree automatiquement si inexistant
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True, parents=True)

# URL de connexion SQLite
DATABASE_URL = f"sqlite:///{DATA_DIR}/cineorg.db"

# Engine SQLite avec check_same_thread=False pour usage multi-thread/async
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def get_session() -> Generator[Session, None, None]:
    """
    Generateur de session SQLModel.

    Utilisation avec next() ou dans une boucle for :
        session = next(get_session())
        try:
            # operations
        finally:
            session.close()

    Ou avec context manager :
        with Session(engine) as session:
            # operations

    Yields:
        Session SQLModel connectee a l'engine SQLite
    """
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """
    Initialise la base de donnees en creant toutes les tables.

    Cette fonction importe les modeles pour enregistrer leurs metadonnees
    dans SQLModel.metadata, puis cree les tables correspondantes si elles
    n'existent pas deja.

    Doit etre appelee une fois au demarrage de l'application.
    """
    # Import des modeles pour enregistrer leurs metadonnees
    # L'import est fait ici pour eviter les imports circulaires
    from src.infrastructure.persistence import models  # noqa: F401

    # Creation des tables
    SQLModel.metadata.create_all(engine)
