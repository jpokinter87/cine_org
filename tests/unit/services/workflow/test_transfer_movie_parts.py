"""Creation des MoviePart a l'execution du transfert."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.services.workflow.transfer_step import TransferStepMixin


class _FakeContainer:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


class _Holder(TransferStepMixin):
    def __init__(self, container):
        self._container = container


def test_transfert_cree_les_movie_parts():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    movie = MovieModel(title="Nos meilleures années", year=2003, tmdb_id=11659)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    holder = _Holder(_FakeContainer(session))

    transfers = [
        {  # Partie 1 : primaire
            "movie_id": movie.id,
            "destination": Path("/storage/Nos meilleures années (2003) Partie 1.mkv"),
            "symlink_destination": Path(
                "/video/Nos meilleures années (2003) Partie 1.mkv"
            ),
        },
        {  # Partie 2 : MoviePart
            "movie_id": movie.id,
            "movie_part_number": 2,
            "destination": Path("/storage/Nos meilleures années (2003) Partie 2.mkv"),
            "symlink_destination": Path(
                "/video/Nos meilleures années (2003) Partie 2.mkv"
            ),
        },
    ]
    results = [{"success": True}, {"success": True}]

    holder._update_file_paths(transfers, results)

    movie = session.get(MovieModel, movie.id)
    assert movie.file_path.endswith("Partie 1.mkv")

    parts = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    assert len(parts) == 1
    assert parts[0].part_number == 2
    assert parts[0].file_path.endswith("Partie 2.mkv")
    assert parts[0].symlink_path.endswith("Partie 2.mkv")
