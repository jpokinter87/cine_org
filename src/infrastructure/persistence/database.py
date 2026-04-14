"""
Configuration de la base de donnees SQLite pour CineOrg.

Ce module fournit :
- Engine SQLite avec configuration optimisee pour multi-thread
- Session factory avec context manager
- Fonction d'initialisation des tables

La base de donnees est configuree via CINEORG_DATABASE_URL (defaut: sqlite:///cineorg.db).
"""

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

# Engine global - initialise lors du premier appel a get_engine()
_engine: Optional[Engine] = None


@event.listens_for(Engine, "connect")
def _register_sqlite_udfs(dbapi_connection, connection_record) -> None:
    """
    Enregistre les UDF SQLite sur chaque connexion DBAPI.

    - ``unaccent(text)`` : supprime les diacritiques (é→e, œuvre→œuvre).
      Utilise ``src.utils.helpers.normalize_accents`` (NFD + filtre Mn).
      Permet une recherche SQL insensible aux accents (phase 43-01).

    ``deterministic=True`` autorise l'usage dans les index et le cache
    de requete (requiert Python 3.8+ et SQLite 3.8.3+ — OK en 2026).
    Fallback silencieux sans le flag si l'environnement est trop ancien.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    from src.utils.helpers import normalize_accents

    def _safe_unaccent(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        return normalize_accents(text)

    try:
        dbapi_connection.create_function(
            "unaccent", 1, _safe_unaccent, deterministic=True
        )
    except TypeError:
        # Ancienne version : signature sans deterministic
        dbapi_connection.create_function("unaccent", 1, _safe_unaccent)


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
            poolclass=NullPool,
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

    with engine.connect() as conn:
        # Migration 1: Ajouter symlink_path a video_files si manquante
        result = conn.execute(text("PRAGMA table_info(video_files)"))
        columns = [row[1] for row in result.fetchall()]

        if "symlink_path" not in columns:
            conn.execute(
                text("ALTER TABLE video_files ADD COLUMN symlink_path VARCHAR")
            )
            conn.commit()

        # Migration 2: Ajouter vote_average et vote_count a movies si manquantes
        result = conn.execute(text("PRAGMA table_info(movies)"))
        movie_columns = [row[1] for row in result.fetchall()]

        if "vote_average" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN vote_average REAL")
            )
            conn.commit()

        if "vote_count" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN vote_count INTEGER")
            )
            conn.commit()

        # Migration 3: Ajouter vote_average et vote_count a series si manquantes
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "vote_average" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN vote_average REAL")
            )
            conn.commit()

        if "vote_count" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN vote_count INTEGER")
            )
            conn.commit()

        # Migration 4: Ajouter imdb_rating et imdb_votes a movies si manquantes
        result = conn.execute(text("PRAGMA table_info(movies)"))
        movie_columns = [row[1] for row in result.fetchall()]

        if "imdb_rating" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN imdb_rating REAL")
            )
            conn.commit()

        if "imdb_votes" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN imdb_votes INTEGER")
            )
            conn.commit()

        # Migration 5: Ajouter imdb_rating et imdb_votes a series si manquantes
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "imdb_rating" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN imdb_rating REAL")
            )
            conn.commit()

        if "imdb_votes" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN imdb_votes INTEGER")
            )
            conn.commit()

        # Migration 6: Ajouter tmdb_id a series si manquante
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "tmdb_id" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN tmdb_id INTEGER")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_series_tmdb_id ON series(tmdb_id)")
            )
            conn.commit()

        # Migration 7: Ajouter watched et personal_rating a movies si manquantes
        result = conn.execute(text("PRAGMA table_info(movies)"))
        movie_columns = [row[1] for row in result.fetchall()]

        if "watched" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN watched BOOLEAN DEFAULT 0")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_movies_watched ON movies(watched)")
            )
            conn.commit()

        if "personal_rating" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN personal_rating INTEGER")
            )
            conn.commit()

        # Migration 8: Ajouter watched et personal_rating a series si manquantes
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "watched" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN watched BOOLEAN DEFAULT 0")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_series_watched ON series(watched)")
            )
            conn.commit()

        if "personal_rating" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN personal_rating INTEGER")
            )
            conn.commit()

        # Migration 9: Ajouter collection_id et collection_name a movies si manquantes
        result = conn.execute(text("PRAGMA table_info(movies)"))
        movie_columns = [row[1] for row in result.fetchall()]

        if "collection_id" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN collection_id INTEGER")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_movies_collection_id ON movies(collection_id)")
            )
            conn.commit()

        if "collection_name" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN collection_name VARCHAR")
            )
            conn.commit()

        # Migration 10: Ajouter is_extra a episodes si manquante
        # (Phase 42-01 : episodes hors canon des decoupages alternatifs)
        result = conn.execute(text("PRAGMA table_info(episodes)"))
        episode_columns = [row[1] for row in result.fetchall()]

        if "is_extra" not in episode_columns:
            conn.execute(
                text(
                    "ALTER TABLE episodes ADD COLUMN is_extra "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_episodes_is_extra "
                    "ON episodes(is_extra)"
                )
            )
            conn.commit()

        # Migration 11: Overrides manuels sur movies (phase 42-02)
        result = conn.execute(text("PRAGMA table_info(movies)"))
        movie_columns = [row[1] for row in result.fetchall()]

        if "poster_override" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN poster_override VARCHAR")
            )
            conn.commit()
        if "overview_override" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN overview_override VARCHAR")
            )
            conn.commit()
        if "cast_override_json" not in movie_columns:
            conn.execute(
                text("ALTER TABLE movies ADD COLUMN cast_override_json VARCHAR")
            )
            conn.commit()
        if "preserve_overrides" not in movie_columns:
            conn.execute(
                text(
                    "ALTER TABLE movies ADD COLUMN preserve_overrides "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_movies_preserve_overrides "
                    "ON movies(preserve_overrides)"
                )
            )
            conn.commit()

        # Migration 12: Overrides manuels sur series (phase 42-02)
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "poster_override" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN poster_override VARCHAR")
            )
            conn.commit()
        if "overview_override" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN overview_override VARCHAR")
            )
            conn.commit()
        if "cast_override_json" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN cast_override_json VARCHAR")
            )
            conn.commit()
        if "preserve_overrides" not in series_columns:
            conn.execute(
                text(
                    "ALTER TABLE series ADD COLUMN preserve_overrides "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_series_preserve_overrides "
                    "ON series(preserve_overrides)"
                )
            )
            conn.commit()
