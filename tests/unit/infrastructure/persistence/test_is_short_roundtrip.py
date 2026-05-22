"""Tests : roundtrip is_short via MovieRepository + migration 13."""

from sqlalchemy import create_engine, text
from sqlmodel import Session, SQLModel

from src.core.entities.media import Movie
from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository as MovieRepository,
)


def _make_engine():
    """Engine in-memory avec tables créées."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestMovieRepositoryIsShortRoundtrip:
    """is_short doit être préservé lors de save() puis get()."""

    def test_save_then_get_preserves_is_short_true(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = MovieRepository(session)
            movie = Movie(
                tmdb_id=999,
                title="Pluto's Dream House",
                year=1940,
                is_short=True,
            )
            saved = repo.save(movie)
            session.commit()

        with Session(engine) as session:
            repo = MovieRepository(session)
            fetched = repo.get_by_tmdb_id(999)
            assert fetched is not None
            assert fetched.is_short is True
            # sanity : id transmis
            assert fetched.id == saved.id

    def test_save_then_get_preserves_is_short_false_default(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = MovieRepository(session)
            movie = Movie(tmdb_id=998, title="Avatar", year=2009)
            repo.save(movie)
            session.commit()

        with Session(engine) as session:
            repo = MovieRepository(session)
            fetched = repo.get_by_tmdb_id(998)
            assert fetched is not None
            assert fetched.is_short is False


class TestMigration13IsShort:
    """La migration 13 doit ajouter la colonne is_short sur movies."""

    def test_migration_adds_is_short_column_to_existing_table(self, tmp_path) -> None:
        """Simule une DB pré-existante sans is_short, puis applique la migration."""
        db_file = tmp_path / "cineorg.db"
        import src.infrastructure.persistence.database as database_module

        original_engine = database_module._engine
        try:
            # 1) Créer toutes les tables (schéma courant inclut is_short)
            database_module._engine = create_engine(f"sqlite:///{db_file}")
            SQLModel.metadata.create_all(database_module._engine)

            # 2) Supprimer is_short pour simuler une DB legacy
            with database_module._engine.connect() as conn:
                conn.execute(text("DROP INDEX IF EXISTS ix_movies_is_short"))
                conn.execute(text("ALTER TABLE movies DROP COLUMN is_short"))
                conn.commit()

            with database_module._engine.connect() as conn:
                cols = [
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(movies)")
                    ).fetchall()
                ]
            assert "is_short" not in cols

            # 3) Lancer la migration : la colonne doit revenir
            database_module._run_migrations()

            with database_module._engine.connect() as conn:
                cols = [
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(movies)")
                    ).fetchall()
                ]
                indexes = [
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA index_list(movies)")
                    ).fetchall()
                ]
            assert "is_short" in cols
            assert "ix_movies_is_short" in indexes

            # 4) Idempotence : re-runner ne doit pas casser
            database_module._run_migrations()
        finally:
            database_module._engine.dispose()
            database_module._engine = original_engine
