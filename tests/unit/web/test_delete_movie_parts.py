"""La suppression d'un film retire aussi ses parties (symlink + ligne)."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.routes.library.delete import _delete_movie_record


class _FakeFS:
    def __init__(self):
        self.removed = []

    def remove_symlink(self, path: Path):
        self.removed.append(str(path))


def test_suppression_film_retire_ses_parties():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    movie = MovieModel(
        title="Film",
        year=2003,
        tmdb_id=1,
        file_path="/storage/Film Partie 1.mkv",
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)
    session.add(
        MoviePartModel(
            movie_id=movie.id,
            part_number=2,
            file_path="/storage/Film Partie 2.mkv",
            symlink_path="/video/Film Partie 2.mkv",
        )
    )
    session.commit()

    fs = _FakeFS()
    _delete_movie_record(session, movie, fs, "test")
    session.commit()

    remaining = session.exec(select(MoviePartModel)).all()
    assert remaining == []
    assert "/video/Film Partie 2.mkv" in fs.removed
