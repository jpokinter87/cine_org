"""Tests : le renvoi en validation nettoie les fiches créées par la préparation.

La préparation du transfert (``/transfer/prepare``) enregistre séries,
épisodes et films en base avant tout déplacement de fichier. Si l'utilisateur
renvoie ensuite l'élément en validation (mauvais match), ces fiches sans
fichier restaient en place : cas « Spider-Noir » associé à tort à « Noire »,
dont la fiche fantôme est restée dans la bibliothèque.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
    TrashModel,
)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


def _make_client(engine, monkeypatch, transfers, candidate_id="cand"):
    from src.web.routes import transfer as transfer_mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(transfer_mod, "get_session", _fake_get_session)

    pendings = {t["pending"].id: t["pending"] for t in transfers}
    validation_service = MagicMock()
    validation_service.get_pending_by_id.side_effect = lambda pid: pendings.get(pid)
    validation_service.list_validated.return_value = list(pendings.values())

    app = FastAPI()
    app.include_router(transfer_mod.router)
    container = MagicMock()
    container.validation_service.return_value = validation_service
    container.file_system.return_value = MagicMock()
    app.state.container = container
    app.state.transfer_batch = transfers
    return TestClient(app), app


def _pending(pid: str, candidate_id: str = "cand"):
    return SimpleNamespace(id=pid, selected_candidate_id=candidate_id)


def _series_with_episodes(engine, *, filed: bool, count: int = 2):
    with Session(engine) as s:
        series = SeriesModel(title="Noire", year=2026, tvdb_id=999)
        s.add(series)
        s.commit()
        s.refresh(series)
        ids = []
        for n in range(1, count + 1):
            ep = EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=n,
                title=f"E{n}",
                file_path=f"/storage/s01e{n:02d}.mkv" if filed else None,
            )
            s.add(ep)
            s.commit()
            s.refresh(ep)
            ids.append(ep.id)
        return series.id, ids


def _series_transfer(pid, series_id, episode_id, created=True):
    return {
        "pending": _pending(pid),
        "is_series": True,
        "series_id": series_id,
        "episode_id": episode_id,
        "created_episode": created,
    }


def test_send_back_trashes_phantom_series_created_by_prepare(engine, monkeypatch):
    series_id, ep_ids = _series_with_episodes(engine, filed=False)
    transfers = [
        _series_transfer("p1", series_id, ep_ids[0]),
        _series_transfer("p2", series_id, ep_ids[1]),
    ]
    client, app = _make_client(engine, monkeypatch, transfers)

    resp = client.post("/transfer/send-back/p1")

    assert resp.status_code == 200
    with Session(engine) as s:
        assert s.get(SeriesModel, series_id) is None
        assert s.exec(select(EpisodeModel)).all() == []
        trashed = s.exec(select(TrashModel)).all()
        assert any(t.entity_type == "series" for t in trashed)
    # Les éléments renvoyés ne figurent plus dans le batch en mémoire
    assert app.state.transfer_batch == []


def test_send_back_keeps_series_with_real_files(engine, monkeypatch):
    """Nouvel épisode d'une série déjà en bibliothèque : seul l'épisode créé
    par la préparation disparaît, la série et ses fichiers restent."""
    series_id, ep_ids = _series_with_episodes(engine, filed=True)
    with Session(engine) as s:
        new_ep = EpisodeModel(
            series_id=series_id, season_number=1, episode_number=3, title="E3"
        )
        s.add(new_ep)
        s.commit()
        s.refresh(new_ep)
        new_ep_id = new_ep.id
    transfers = [
        _series_transfer("p1", series_id, new_ep_id, created=True),
        # Remplacement d'un épisode existant : jamais supprimé
        _series_transfer("p2", series_id, ep_ids[0], created=False),
    ]
    client, _ = _make_client(engine, monkeypatch, transfers)

    client.post("/transfer/send-back/p1")

    with Session(engine) as s:
        assert s.get(SeriesModel, series_id) is not None
        assert s.get(EpisodeModel, new_ep_id) is None
        assert s.get(EpisodeModel, ep_ids[0]) is not None
        assert s.get(EpisodeModel, ep_ids[1]) is not None


def test_send_back_keeps_preexisting_unfiled_episode(engine, monkeypatch):
    """Un épisode sans fichier qui existait avant la préparation n'est pas
    supprimé tant que la série possède des fichiers."""
    series_id, _ = _series_with_episodes(engine, filed=True)
    with Session(engine) as s:
        old = EpisodeModel(
            series_id=series_id, season_number=2, episode_number=1, title="Vieux"
        )
        s.add(old)
        s.commit()
        s.refresh(old)
        old_id = old.id
    transfers = [_series_transfer("p1", series_id, old_id, created=False)]
    client, _ = _make_client(engine, monkeypatch, transfers)

    client.post("/transfer/send-back/p1")

    with Session(engine) as s:
        assert s.get(EpisodeModel, old_id) is not None


def test_send_back_trashes_unfiled_movie(engine, monkeypatch):
    with Session(engine) as s:
        movie = MovieModel(title="Mauvais film", year=2026, tmdb_id=42)
        s.add(movie)
        s.commit()
        s.refresh(movie)
        movie_id = movie.id
    transfers = [{"pending": _pending("p1"), "is_series": False, "movie_id": movie_id}]
    client, _ = _make_client(engine, monkeypatch, transfers)

    client.post("/transfer/send-back/p1")

    with Session(engine) as s:
        assert s.get(MovieModel, movie_id) is None


def test_send_back_keeps_movie_with_file(engine, monkeypatch):
    with Session(engine) as s:
        movie = MovieModel(
            title="Film en place", year=2020, tmdb_id=43, file_path="/storage/f.mkv"
        )
        s.add(movie)
        s.commit()
        s.refresh(movie)
        movie_id = movie.id
    transfers = [{"pending": _pending("p1"), "is_series": False, "movie_id": movie_id}]
    client, _ = _make_client(engine, monkeypatch, transfers)

    client.post("/transfer/send-back/p1")

    with Session(engine) as s:
        assert s.get(MovieModel, movie_id) is not None


def test_send_back_without_batch_still_works(engine, monkeypatch):
    """Sans batch en mémoire (redémarrage), le renvoi fonctionne sans nettoyage."""
    transfers = [{"pending": _pending("p1"), "is_series": False, "movie_id": 1}]
    client, app = _make_client(engine, monkeypatch, transfers)
    app.state.transfer_batch = None

    resp = client.post("/transfer/send-back/p1")

    assert resp.status_code == 200
