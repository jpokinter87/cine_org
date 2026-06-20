"""La fiche film expose ses parties (MoviePart) au template."""

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.app import app


def _setup_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine  # force get_session/get_engine onto the test DB
    with Session(engine) as s:
        movie = MovieModel(
            title="Nos meilleures années",
            year=2003,
            tmdb_id=11659,
            file_path="/storage/Nos meilleures années (2003) Partie 1.mkv",
        )
        s.add(movie)
        s.commit()
        s.refresh(movie)
        s.add(
            MoviePartModel(
                movie_id=movie.id,
                part_number=2,
                file_path="/storage/Nos meilleures années (2003) Partie 2.mkv",
                symlink_path="/video/Nos meilleures années (2003) Partie 2.mkv",
            )
        )
        s.commit()
        return movie.id


def test_fiche_film_affiche_le_bloc_parties(tmp_path):
    movie_id = _setup_db(tmp_path)
    client = TestClient(app)
    resp = client.get(f"/library/movies/{movie_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Parties" in body
    assert "Partie 1" in body
    assert "Partie 2" in body
    assert "/library/movie-parts/" in body
