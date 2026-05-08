"""
Tests d'integration legers pour la sync IMDb (films + series).

On verifie via une session SQLite en memoire que la fonction de sync :
- met a jour imdb_rating + imdb_votes pour MovieModel sans note
- met a jour imdb_rating + imdb_votes pour SeriesModel sans note
- ignore les entites sans imdb_id ou avec une note deja presente
"""

from sqlmodel import Session, SQLModel, create_engine

from src.adapters.cli.commands.imdb_commands import _sync_imdb_for_model
from src.infrastructure.persistence.models import (
    IMDbRatingModel,
    MovieModel,
    SeriesModel,
)


class _FakeImporter:
    """Mock importer : table en memoire imdb_id -> (rating, votes)."""

    def __init__(self, table: dict[str, tuple[float, int]]) -> None:
        self._table = table

    def get_rating(self, imdb_id: str):
        return self._table.get(imdb_id)


def _make_session() -> Session:
    """Cree une session SQLite en memoire avec les tables necessaires."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_sync_imdb_for_series_updates_ratings():
    """Une serie avec imdb_id mais sans note voit sa note synchronisee."""
    session = _make_session()
    series = SeriesModel(
        tvdb_id=12345,
        title="Forever",
        year=1996,
        imdb_id="tt0123456",
    )
    session.add(series)
    session.commit()

    importer = _FakeImporter({"tt0123456": (8.2, 9876)})

    synced, not_found = _sync_imdb_for_model(
        session=session,
        model_class=SeriesModel,
        importer=importer,
        limit=10,
    )

    assert synced == 1
    assert not_found == 0

    refreshed = session.get(SeriesModel, series.id)
    assert refreshed.imdb_rating == 8.2
    assert refreshed.imdb_votes == 9876


def test_sync_imdb_for_series_skips_already_rated():
    """Les series avec imdb_rating deja peuple ne sont pas re-traitees."""
    session = _make_session()
    s1 = SeriesModel(
        tvdb_id=1, title="Already", year=2010, imdb_id="tt1", imdb_rating=7.0,
    )
    s2 = SeriesModel(tvdb_id=2, title="Pending", year=2011, imdb_id="tt2")
    session.add(s1)
    session.add(s2)
    session.commit()

    importer = _FakeImporter({"tt1": (8.0, 100), "tt2": (6.5, 200)})

    synced, _ = _sync_imdb_for_model(
        session=session, model_class=SeriesModel, importer=importer, limit=10,
    )

    assert synced == 1
    refreshed_s1 = session.get(SeriesModel, s1.id)
    refreshed_s2 = session.get(SeriesModel, s2.id)
    # s1 inchangee (deja notee)
    assert refreshed_s1.imdb_rating == 7.0
    assert refreshed_s1.imdb_votes is None
    # s2 mise a jour
    assert refreshed_s2.imdb_rating == 6.5
    assert refreshed_s2.imdb_votes == 200


def test_sync_imdb_for_series_counts_not_found():
    """Quand le cache n'a pas l'imdb_id, on compte not_found et on n'ecrit pas."""
    session = _make_session()
    series = SeriesModel(
        tvdb_id=1, title="Mystere", year=2020, imdb_id="tt9999999",
    )
    session.add(series)
    session.commit()

    importer = _FakeImporter({})  # cache vide

    synced, not_found = _sync_imdb_for_model(
        session=session, model_class=SeriesModel, importer=importer, limit=10,
    )

    assert synced == 0
    assert not_found == 1
    refreshed = session.get(SeriesModel, series.id)
    assert refreshed.imdb_rating is None


def test_sync_imdb_for_movies_still_works():
    """Verifier que la sync films reste fonctionnelle apres la generalisation."""
    session = _make_session()
    movie = MovieModel(
        tmdb_id=42, title="Inception", year=2010, imdb_id="tt1375666",
    )
    session.add(movie)
    session.commit()

    importer = _FakeImporter({"tt1375666": (8.8, 200000)})

    synced, _ = _sync_imdb_for_model(
        session=session, model_class=MovieModel, importer=importer, limit=10,
    )

    assert synced == 1
    refreshed = session.get(MovieModel, movie.id)
    assert refreshed.imdb_rating == 8.8
    assert refreshed.imdb_votes == 200000
