"""Diffusion d'un fichier vidéo vers un téléphone (lecture dans VLC).

Le navigateur du téléphone ne sait pas lire une bonne partie de la vidéothèque
(son AC3/DTS, MKV, HEVC) : CineOrg diffuse le fichier tel quel et VLC le lit.
La route doit accepter les requêtes partielles (Range) pour l'avance rapide.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import src.web.routes.library.player as player
from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from src.web.app import app

CONTENT = b"0123456789" * 10


@pytest.fixture
def video(tmp_path):
    """Fichier physique et lien symbolique qui le désigne."""
    physical = tmp_path / "NAS64" / "Film.mkv"
    physical.parent.mkdir()
    physical.write_bytes(CONTENT)
    link = tmp_path / "video" / "Film (2026).mkv"
    link.parent.mkdir()
    link.symlink_to(physical)
    return physical, link


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(eng)
    database._engine = eng
    return eng


def _add(engine, obj):
    with Session(engine) as s:
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj.id


def _series_with_episode(engine, path) -> tuple[int, int]:
    series_id = _add(engine, SeriesModel(title="Chernobyl", year=2019))
    ep_id = _add(
        engine,
        EpisodeModel(
            series_id=series_id,
            season_number=1,
            episode_number=1,
            title="1:23:45",
            file_path=path,
        ),
    )
    return series_id, ep_id


def test_stream_episode_returns_file(engine, video):
    physical, _ = video
    _, ep_id = _series_with_episode(engine, str(physical))

    resp = TestClient(app).get(f"/library/episodes/{ep_id}/stream")

    assert resp.status_code == 200
    assert resp.content == CONTENT
    assert resp.headers["content-type"].startswith("video/")


def test_stream_supports_range_requests(engine, video):
    physical, _ = video
    _, ep_id = _series_with_episode(engine, str(physical))

    resp = TestClient(app).get(
        f"/library/episodes/{ep_id}/stream", headers={"Range": "bytes=10-19"}
    )

    assert resp.status_code == 206
    assert resp.content == CONTENT[10:20]


def test_stream_movie_follows_symlink(engine, video):
    _, link = video
    movie_id = _add(engine, MovieModel(title="Film", year=2026, file_path=str(link)))

    resp = TestClient(app).get(f"/library/movies/{movie_id}/stream")

    assert resp.status_code == 200
    assert resp.content == CONTENT


def test_stream_movie_part(engine, video):
    physical, _ = video
    movie_id = _add(engine, MovieModel(title="Film", year=2026))
    part_id = _add(
        engine,
        MoviePartModel(movie_id=movie_id, part_number=2, file_path=str(physical)),
    )

    resp = TestClient(app).get(f"/library/movie-parts/{part_id}/stream")

    assert resp.content == CONTENT


def test_stream_series_plays_first_episode(engine, video):
    physical, _ = video
    series_id, _ = _series_with_episode(engine, str(physical))

    resp = TestClient(app).get(f"/library/series/{series_id}/stream")

    assert resp.content == CONTENT


def test_stream_unknown_entity_is_404(engine):
    assert TestClient(app).get("/library/episodes/999/stream").status_code == 404


def test_stream_missing_file_is_404(engine, tmp_path):
    _, ep_id = _series_with_episode(engine, str(tmp_path / "absent.mkv"))

    assert TestClient(app).get(f"/library/episodes/{ep_id}/stream").status_code == 404


def test_play_menu_offers_vlc_option(monkeypatch):
    """Le bouton restauré après lecture propose aussi « Sur ce téléphone (VLC) »."""
    monkeypatch.setattr(
        player,
        "load_profiles",
        lambda: {"profiles": [{"name": "Local"}, {"name": "DuneHD", "type": "dunehd"}]},
    )

    html = player._play_button_html("episodes", 42)

    assert 'data-stream="/library/episodes/42/stream"' in html
    assert "play-option-vlc" in html
