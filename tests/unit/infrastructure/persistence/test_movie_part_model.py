"""Tests du modèle MoviePartModel (parties d'un film multi-parties)."""

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_movie_part_persiste_et_se_relit():
    session = _session()
    movie = MovieModel(title="Nos meilleures années", year=2003, tmdb_id=11659)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    part = MoviePartModel(
        movie_id=movie.id,
        part_number=2,
        file_path="/storage/Nos meilleures années (2003) Partie 2.mkv",
        symlink_path="/video/Nos meilleures années (2003) Partie 2.mkv",
    )
    session.add(part)
    session.commit()

    rows = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].part_number == 2
    assert rows[0].file_path.endswith("Partie 2.mkv")
    assert rows[0].symlink_path.endswith("Partie 2.mkv")
