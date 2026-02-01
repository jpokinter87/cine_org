"""
Configuration de la base de donnees SQLite pour CineOrg.

Ce module fournit :
- Engine SQLite avec configuration optimisee pour multi-thread
- Session factory avec context manager
- Fonction d'initialisation des tables

La base de donnees est configuree via CINEORG_DATABASE_URL (defaut: sqlite:///cineorg.db).
"""

from collections.abc import Generator
from pathlib import Path
from typing import Optional

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import Engine

# Engine global - initialise lors du premier appel a get_engine()
_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """
    Retourne l'engine SQLite, en le creant si necessaire.

    Utilise la configuration de l'application pour le chemin de la BDD.
    """
    global _engine
    if _engine is None:
        from src.config import Settings
        settings = Settings()

        # Creer le repertoire parent si l'URL est un fichier SQLite
        db_url = settings.database_url
        if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:///:memory:"):
            db_path = Path(db_url.replace("sqlite:///", ""))
            db_path.parent.mkdir(exist_ok=True, parents=True)

        _engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine




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
        with Session(get_engine()) as session:
            # operations

    Yields:
        Session SQLModel connectee a l'engine SQLite
    """
    with Session(get_engine()) as session:
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
    SQLModel.metadata.create_all(get_engine())

    # Migrations automatiques
    _run_migrations()


def _run_migrations() -> None:
    """
    Execute les migrations de schema necessaires.

    Verifie et ajoute les colonnes manquantes dans les tables existantes.
    SQLModel.metadata.create_all() ne modifie pas les tables existantes,
    donc cette fonction est necessaire pour les mises a jour de schema.
    """
    from sqlalchemy import text

    engine = get_engine()

    # Migration 1: Ajouter symlink_path a video_files si manquante
    with engine.connect() as conn:
        # Verifier si la colonne existe
        result = conn.execute(text("PRAGMA table_info(video_files)"))
        columns = [row[1] for row in result.fetchall()]

        if "symlink_path" not in columns:
            conn.execute(
                text("ALTER TABLE video_files ADD COLUMN symlink_path VARCHAR")
            )
            conn.commit()
