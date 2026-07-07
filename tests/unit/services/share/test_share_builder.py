from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import EpisodeModel, MovieModel, SeriesModel
from src.services.share.builder import JellyfinShareBuilder
from src.services.share.exceptions import ShareError


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _physical(tmp_path: Path, name: str) -> Path:
    f = tmp_path / name
    f.write_bytes(b"x")
    return f


def test_populate_movie_creates_symlink_and_nfo(tmp_path):
    src = _physical(tmp_path, "film.mkv")
    session = _session()
    movie = MovieModel(title="Inception", year=2010, tmdb_id=27205, file_path=str(src), symlink_path=None)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    partage = tmp_path / "Partage"
    builder = JellyfinShareBuilder(session, partage)
    folder = builder.populate_movie(movie.id)

    assert folder == "Inception (2010)"
    movie_dir = partage / "Films" / "Inception (2010)"
    link = movie_dir / "Inception (2010).mkv"
    assert link.is_symlink()
    assert link.resolve() == src.resolve()
    assert (movie_dir / "movie.nfo").exists()


def test_populate_movie_missing_source_raises(tmp_path):
    session = _session()
    movie = MovieModel(title="X", year=2000, file_path="/nope.mkv", symlink_path=None)
    session.add(movie)
    session.commit()
    session.refresh(movie)
    builder = JellyfinShareBuilder(session, tmp_path / "Partage")
    try:
        builder.populate_movie(movie.id)
        assert False, "devait lever ShareError"
    except ShareError:
        pass


def test_populate_series_creates_seasons(tmp_path):
    s1 = _physical(tmp_path, "e1.mkv")
    s2 = _physical(tmp_path, "e2.mkv")
    session = _session()
    series = SeriesModel(title="Gomorra", year=2014, tvdb_id=272135)
    session.add(series)
    session.commit()
    session.refresh(series)
    session.add(EpisodeModel(series_id=series.id, season_number=1, episode_number=1, title="P", file_path=str(s1), symlink_path=None))
    session.add(EpisodeModel(series_id=series.id, season_number=1, episode_number=2, title="D", file_path=str(s2), symlink_path=None))
    session.commit()

    partage = tmp_path / "Partage"
    builder = JellyfinShareBuilder(session, partage)
    folder = builder.populate_series(series.id)

    assert folder == "Gomorra (2014)"
    show_dir = partage / "Series" / "Gomorra (2014)"
    assert (show_dir / "tvshow.nfo").exists()
    season = show_dir / "Saison 01"
    links = sorted(p.name for p in season.glob("*.mkv"))
    assert links == ["Gomorra (2014) S01E01.mkv", "Gomorra (2014) S01E02.mkv"]


def test_clear_removes_films_and_series(tmp_path):
    partage = tmp_path / "Partage"
    (partage / "Films" / "a").mkdir(parents=True)
    (partage / "Series" / "b").mkdir(parents=True)
    builder = JellyfinShareBuilder(_session(), partage)
    builder.clear()
    assert not (partage / "Films").exists()
    assert not (partage / "Series").exists()
