"""Endpoint POST /library/movie-parts/{id}/play."""

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.app import app


def _setup(tmp_path, real_file):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine
    with Session(engine) as s:
        movie = MovieModel(title="Film", year=2003, tmdb_id=1)
        s.add(movie)
        s.commit()
        s.refresh(movie)
        part = MoviePartModel(
            movie_id=movie.id,
            part_number=2,
            file_path=str(real_file),
            symlink_path=str(real_file),
        )
        s.add(part)
        s.commit()
        s.refresh(part)
        return part.id


def test_play_partie_inconnue_renvoie_404(tmp_path):
    _setup(tmp_path, tmp_path / "dummy.mkv")
    client = TestClient(app)
    resp = client.post("/library/movie-parts/99999/play")
    assert resp.status_code == 404


def test_play_partie_lance_le_lecteur(tmp_path, monkeypatch):
    real = tmp_path / "Film (2003) Partie 2.mkv"
    real.write_bytes(b"x")
    part_id = _setup(tmp_path, real)

    import src.web.routes.library.player as player

    launched = {}

    def fake_launch(path, profile_name=None):
        launched["path"] = str(path)
        return 4242, None, "mpv"

    monkeypatch.setattr(player, "_launch_player", fake_launch)

    client = TestClient(app)
    resp = client.post(f"/library/movie-parts/{part_id}/play")
    assert resp.status_code == 200
    assert launched["path"].endswith("Partie 2.mkv")
