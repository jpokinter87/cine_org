"""Tests P4 — LocalCollection entity, model, repository."""

from sqlalchemy import create_engine, text
from sqlmodel import Session, SQLModel

from src.core.entities.local_collection import LocalCollection
from src.core.entities.media import Movie
from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel
from src.infrastructure.persistence.repositories.local_collection_repository import (
    SQLModelLocalCollectionRepository,
)
from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository,
)


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestLocalCollectionEntity:
    """Champs et défauts de l'entité de domaine."""

    def test_minimal_construction(self) -> None:
        coll = LocalCollection(name="Looney Tunes")
        assert coll.name == "Looney Tunes"
        assert coll.id is None
        assert coll.description is None

    def test_with_description(self) -> None:
        coll = LocalCollection(
            name="Cartoons Hanna-Barbera",
            description="Tom & Jerry, Yogi, Scooby-Doo",
        )
        assert coll.description == "Tom & Jerry, Yogi, Scooby-Doo"


class TestLocalCollectionModel:
    """Persistance SQLModel."""

    def test_model_save_and_query(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            model = LocalCollectionModel(name="Pixar Shorts")
            session.add(model)
            session.commit()
            session.refresh(model)
            assert model.id is not None
            assert model.name == "Pixar Shorts"


class TestMovieLocalCollectionFK:
    """Movie ↔ LocalCollection via FK."""

    def test_movie_with_local_collection_id(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            coll = LocalCollectionModel(name="Looney Tunes")
            session.add(coll)
            session.commit()
            session.refresh(coll)

            movie = MovieModel(
                title="Hare-Way to the Stars",
                duration_seconds=420,
                is_short=True,
                local_collection_id=coll.id,
            )
            session.add(movie)
            session.commit()
            session.refresh(movie)
            assert movie.local_collection_id == coll.id


class TestMovieRepositoryWithLocalCollection:
    """Roundtrip entité Movie avec local_collection_name peuplé depuis FK."""

    def test_entity_has_local_collection_name_when_assigned(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            coll = LocalCollectionModel(name="Looney Tunes")
            session.add(coll)
            session.commit()
            session.refresh(coll)
            coll_id = coll.id

            repo = SQLModelMovieRepository(session)
            movie = Movie(
                tmdb_id=42,
                title="Hare-Way",
                year=1958,
                duration_seconds=420,
                is_short=True,
                local_collection_id=coll_id,
            )
            repo.save(movie)
            session.commit()

        with Session(engine) as session:
            repo = SQLModelMovieRepository(session)
            fetched = repo.get_by_tmdb_id(42)
            assert fetched is not None
            assert fetched.local_collection_id == coll_id
            # Le repo charge le nom de la collection locale via join
            assert fetched.local_collection_name == "Looney Tunes"

    def test_entity_local_collection_name_is_none_when_unassigned(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = SQLModelMovieRepository(session)
            repo.save(Movie(tmdb_id=43, title="Sans coll", year=2020))
            session.commit()

        with Session(engine) as session:
            repo = SQLModelMovieRepository(session)
            fetched = repo.get_by_tmdb_id(43)
            assert fetched is not None
            assert fetched.local_collection_id is None
            assert fetched.local_collection_name is None


class TestLocalCollectionRepository:
    """CRUD + listing."""

    def test_save_and_get_by_id(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = SQLModelLocalCollectionRepository(session)
            saved = repo.save(LocalCollection(name="Looney Tunes"))
            assert saved.id is not None

            fetched = repo.get_by_id(saved.id)
            assert fetched is not None
            assert fetched.name == "Looney Tunes"

    def test_get_by_name(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = SQLModelLocalCollectionRepository(session)
            repo.save(LocalCollection(name="Pixar Shorts"))

            fetched = repo.get_by_name("Pixar Shorts")
            assert fetched is not None
            assert fetched.name == "Pixar Shorts"

            assert repo.get_by_name("Inexistante") is None

    def test_list_with_movie_counts(self) -> None:
        engine = _make_engine()
        with Session(engine) as session:
            repo = SQLModelLocalCollectionRepository(session)
            looney = repo.save(LocalCollection(name="Looney Tunes"))
            repo.save(LocalCollection(name="Pixar Shorts"))

            # Ajouter 2 films à Looney, 0 à Pixar
            session.add(
                MovieModel(
                    title="A", duration_seconds=300, local_collection_id=looney.id
                )
            )
            session.add(
                MovieModel(
                    title="B", duration_seconds=400, local_collection_id=looney.id
                )
            )
            session.commit()

            counts = repo.list_with_movie_counts()
            counts_by_name = {c.collection.name: c.movie_count for c in counts}
            assert counts_by_name["Looney Tunes"] == 2
            assert counts_by_name["Pixar Shorts"] == 0


class TestMigrations14And15:
    """Migrations idempotentes : creation + re-run sans erreur."""

    def test_migrations_create_table_and_fk_idempotent(self, tmp_path) -> None:
        """Sur une DB legacy minimale (movies + local_collection_id absente),
        les migrations 14 et 15 ajoutent la table puis la colonne FK."""
        db_file = tmp_path / "cineorg.db"
        import src.infrastructure.persistence.database as database_module

        original_engine = database_module._engine
        try:
            # Schéma legacy : movies sans FK ni la table local_collections.
            database_module._engine = create_engine(f"sqlite:///{db_file}")
            with database_module._engine.connect() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE movies ("
                        "id INTEGER PRIMARY KEY, "
                        "title VARCHAR NOT NULL, "
                        "is_short BOOLEAN NOT NULL DEFAULT 0)"
                    )
                )
                conn.commit()

            with database_module._engine.connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    ).fetchall()
                }
            assert "local_collections" not in tables

            # Crée toutes les tables manquantes (sauf movies legacy), puis migre.
            from src.infrastructure.persistence import models  # noqa: F401

            SQLModel.metadata.create_all(database_module._engine)
            database_module._run_migrations()

            with database_module._engine.connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    ).fetchall()
                }
                cols = {
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(movies)")
                    ).fetchall()
                }
            assert "local_collections" in tables
            assert "local_collection_id" in cols

            # Idempotence
            database_module._run_migrations()
        finally:
            database_module._engine.dispose()
            database_module._engine = original_engine
