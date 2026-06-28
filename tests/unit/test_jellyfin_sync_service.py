"""Tests d'orchestration de JellyfinSyncService."""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from src.services.jellyfin.jellyfin_sync_service import JellyfinSyncService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _make_physical(tmp_path: Path, name: str) -> Path:
    f = tmp_path / "phys" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    return f


def test_sync_movie_creates_tree_and_nfo(engine, tmp_path):
    phys = _make_physical(tmp_path, "Inception (2010).mkv")
    with Session(engine) as session:
        m = MovieModel(
            title="Inception",
            year=2010,
            tmdb_id=27205,
            imdb_id="tt1375666",
            symlink_path=str(phys),
        )
        session.add(m)
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(series_only=False)

    movie_dir = jf / "Films" / "Inception (2010)"
    assert (movie_dir / "Inception (2010).mkv").is_symlink()
    assert (movie_dir / "movie.nfo").exists()
    assert report.movies == 1
    assert "tt1375666" in (movie_dir / "movie.nfo").read_text()


def test_sync_skips_missing_source(engine, tmp_path):
    with Session(engine) as session:
        session.add(
            MovieModel(
                title="Perdu", year=1999, tmdb_id=1, symlink_path="/n/existe/pas.mkv"
            )
        )
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync()

    assert report.movies == 0
    assert len(report.skipped) == 1


def test_sync_multipart_movie(engine, tmp_path):
    p1 = _make_physical(tmp_path, "hobbit1.mkv")
    p2 = _make_physical(tmp_path, "hobbit2.mkv")
    with Session(engine) as session:
        m = MovieModel(
            title="Le Hobbit", year=2012, tmdb_id=49051, symlink_path=str(p1)
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        session.add(MoviePartModel(movie_id=m.id, part_number=1, symlink_path=str(p1)))
        session.add(MoviePartModel(movie_id=m.id, part_number=2, symlink_path=str(p2)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    JellyfinSyncService(Session(engine), jf).sync()

    movie_dir = jf / "Films" / "Le Hobbit (2012)"
    links = sorted(p.name for p in movie_dir.glob("*.mkv"))
    assert len(links) == 2


def test_sync_collision_appends_tmdb_id(engine, tmp_path):
    p1 = _make_physical(tmp_path, "a.mkv")
    p2 = _make_physical(tmp_path, "b.mkv")
    with Session(engine) as session:
        session.add(
            MovieModel(title="Doublon", year=2000, tmdb_id=11, symlink_path=str(p1))
        )
        session.add(
            MovieModel(title="Doublon", year=2000, tmdb_id=22, symlink_path=str(p2))
        )
        session.commit()

    jf = tmp_path / "JellyfinLib"
    JellyfinSyncService(Session(engine), jf).sync()

    films = jf / "Films"
    names = sorted(d.name for d in films.iterdir())
    assert names == ["Doublon (2000)", "Doublon (2000) [tmdbid-22]"]


def test_sync_dry_run_creates_nothing(engine, tmp_path):
    phys = _make_physical(tmp_path, "x.mkv")
    with Session(engine) as session:
        session.add(MovieModel(title="X", year=2001, tmdb_id=3, symlink_path=str(phys)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(dry_run=True)

    assert not (jf / "Films").exists()
    assert report.movies == 1  # compté, mais rien écrit


def test_sync_continues_on_item_error(engine, tmp_path, monkeypatch):
    phys = _make_physical(tmp_path, "ok.mkv")
    with Session(engine) as session:
        session.add(
            MovieModel(title="Bon", year=2000, tmdb_id=1, symlink_path=str(phys))
        )
        session.add(
            MovieModel(title="Mauvais", year=2001, tmdb_id=2, symlink_path=str(phys))
        )
        session.commit()

    import src.services.jellyfin.jellyfin_sync_service as svc

    real_build = svc.build_movie_nfo

    def fake_build(movie):
        if movie.title == "Mauvais":
            raise ValueError("boom")
        return real_build(movie)

    monkeypatch.setattr(svc, "build_movie_nfo", fake_build)

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync()

    assert report.movies == 1  # "Bon" traité malgré l'échec de "Mauvais"
    assert len(report.errors) == 1
    assert "Mauvais" in report.errors[0]


def test_sync_series_and_episodes(engine, tmp_path):
    ep_phys = _make_physical(tmp_path, "ep1.mkv")
    with Session(engine) as session:
        s = SeriesModel(title="12 Monkeys", year=2015, tvdb_id=272644, tmdb_id=60948)
        session.add(s)
        session.commit()
        session.refresh(s)
        session.add(
            EpisodeModel(
                series_id=s.id,
                season_number=1,
                episode_number=1,
                title="Fragmentation",
                symlink_path=str(ep_phys),
            )
        )
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(movies_only=False)

    show_dir = jf / "Séries" / "12 Monkeys (2015)"
    assert (show_dir / "tvshow.nfo").exists()
    season_dir = show_dir / "Saison 01"
    assert (season_dir / "12 Monkeys (2015) S01E01.mkv").is_symlink()
    assert (season_dir / "12 Monkeys (2015) S01E01.nfo").exists()
    assert report.series == 1
    assert report.episodes == 1


def test_sync_series_skips_missing_episode(engine, tmp_path):
    with Session(engine) as session:
        s = SeriesModel(title="Sérieuse", year=2020, tvdb_id=1)
        session.add(s)
        session.commit()
        session.refresh(s)
        session.add(
            EpisodeModel(
                series_id=s.id,
                season_number=1,
                episode_number=1,
                title="Absent",
                symlink_path="/pas/la.mkv",
            )
        )
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync()
    assert report.episodes == 0
    assert len(report.skipped) == 1


def test_prune_removes_stale_entries(engine, tmp_path):
    phys = _make_physical(tmp_path, "ok.mkv")
    with Session(engine) as session:
        session.add(
            MovieModel(title="Garde", year=2000, tmdb_id=1, symlink_path=str(phys))
        )
        session.commit()

    jf = tmp_path / "JellyfinLib"
    stale = jf / "Films" / "Vieux Film (1990)"
    stale.mkdir(parents=True)
    (stale / "x.nfo").write_text("vieux")

    report = JellyfinSyncService(Session(engine), jf).sync(prune=True)

    assert (jf / "Films" / "Garde (2000)").exists()
    assert not stale.exists()
    assert any("Vieux Film" in p for p in report.pruned)
