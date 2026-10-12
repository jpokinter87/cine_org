"""La DuneHD doit recevoir le chemin du lien symbolique, pas celui du fichier physique.

Architecture : les fichiers physiques sont sur le NAS64 ; le serveur de
fichiers (192.168.1.2) héberge les liens symboliques et les partage en Samba
à la DuneHD. Envoyer le chemin physique (`/media/NAS64/…`) produisait une URL
SMB inexistante sur le serveur : la Dune acceptait la commande puis restait
bloquée sur l'horloge (Chernobyl S01E01, Le Bureau des légendes…).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import src.web.routes.library.player as player
from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)
from src.web.app import app

DUNE = {"name": "DuneHD", "type": "dunehd", "ip": "192.168.1.4"}
MPV = {"name": "Local", "type": "mpv", "target": "local", "command": "mpv"}


@pytest.fixture
def files(tmp_path):
    """Fichier physique (stockage) + lien symbolique (arborescence vidéo)."""
    physical = tmp_path / "NAS64" / "Series" / "Chernobyl.S01E01.mkv"
    physical.parent.mkdir(parents=True)
    physical.write_bytes(b"x")
    link = tmp_path / "Serveur" / "Series" / "Chernobyl - S01E01.mkv"
    link.parent.mkdir(parents=True)
    link.symlink_to(physical)
    return physical, link


@pytest.fixture
def launched(monkeypatch):
    """Capture le chemin transmis à la DuneHD ou à mpv, sans rien lancer."""
    sent = {}

    class _FakeDune:
        def __init__(self, profile):
            pass

        def play(self, path):
            sent["dune"] = Path(path)
            return type("R", (), {"ok": True, "error": None})()

    def _fake_local(command, path):
        sent["mpv"] = Path(path)
        return type("P", (), {"pid": 4242})()

    monkeypatch.setattr(player, "DuneHDPlayer", _FakeDune)
    monkeypatch.setattr(player, "_launch_local", _fake_local)
    return sent


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine
    return engine


def _episode(tmp_path, physical, link) -> int:
    with Session(_db(tmp_path)) as s:
        series = SeriesModel(title="Chernobyl", year=2019)
        s.add(series)
        s.commit()
        s.refresh(series)
        ep = EpisodeModel(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="1:23:45",
            file_path=str(physical),
            symlink_path=str(link) if link else None,
        )
        s.add(ep)
        s.commit()
        s.refresh(ep)
        return ep.id


def _movie(tmp_path, physical, link) -> int:
    with Session(_db(tmp_path)) as s:
        movie = MovieModel(
            title="Film", year=2026, file_path=str(physical), symlink_path=str(link)
        )
        s.add(movie)
        s.commit()
        s.refresh(movie)
        return movie.id


def _use(monkeypatch, profile):
    monkeypatch.setattr(player, "get_profile_by_name", lambda name: profile)


def test_dune_receives_episode_symlink(tmp_path, files, launched, monkeypatch):
    physical, link = files
    ep_id = _episode(tmp_path, physical, link)
    _use(monkeypatch, DUNE)

    resp = TestClient(app).post(f"/library/episodes/{ep_id}/play?profile=DuneHD")

    assert resp.status_code == 200
    assert launched["dune"] == link


def test_dune_receives_series_first_episode_symlink(
    tmp_path, files, launched, monkeypatch
):
    physical, link = files
    _episode(tmp_path, physical, link)
    _use(monkeypatch, DUNE)

    TestClient(app).post("/library/series/1/play?profile=DuneHD")

    assert launched["dune"] == link


def test_dune_receives_movie_symlink(tmp_path, files, launched, monkeypatch):
    physical, link = files
    movie_id = _movie(tmp_path, physical, link)
    _use(monkeypatch, DUNE)

    TestClient(app).post(f"/library/movies/{movie_id}/play?profile=DuneHD")

    assert launched["dune"] == link


def test_dune_falls_back_to_physical_without_symlink(
    tmp_path, files, launched, monkeypatch
):
    physical, _ = files
    ep_id = _episode(tmp_path, physical, None)
    _use(monkeypatch, DUNE)

    TestClient(app).post(f"/library/episodes/{ep_id}/play?profile=DuneHD")

    assert launched["dune"] == physical


def test_mpv_still_receives_physical_file(tmp_path, files, launched, monkeypatch):
    physical, link = files
    ep_id = _episode(tmp_path, physical, link)
    _use(monkeypatch, MPV)

    TestClient(app).post(f"/library/episodes/{ep_id}/play?profile=Local")

    assert launched["mpv"] == physical
