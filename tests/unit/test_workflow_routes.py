"""
Tests des routes HTMX d'actions sur les anomalies de decoupage
(phase 42-01, tache 3e).

Couvre les 3 routes POST /workflow/anomalies/{accept,dismiss,trash} :
- accept : cree un SeasonOverrideModel et valide les pendings
- dismiss : ne touche pas la base, retire le groupe de la session
- trash : appelle reject_pending sur chaque pending
- accept : episode_count = max des episode_number du groupe
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.core.entities.video import (
    PendingValidation,
    ValidationStatus,
    VideoFile,
)
from src.infrastructure.persistence.models import SeasonOverrideModel
from src.services.anomaly_detector import ExcessEpisodeGroup
from src.web.routes.workflow import WorkflowProgress, router as workflow_router


TVDB_ID = 246063
SEASON = 4


@pytest.fixture
def engine():
    # StaticPool : toutes les connexions partagent la meme DB in-memory,
    # necessaire quand la route et le test s'executent dans des threads
    # distincts (TestClient FastAPI).
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_pending(ep_num: int, include_target_tvdb: bool = False) -> PendingValidation:
    """Pending S04E{ep_num}.

    Par defaut (include_target_tvdb=False), les candidats ne contiennent
    PAS la serie cible TVDB — refletant le scenario reel ou
    filter_by_episode_count a elimine la bonne serie parce que son canon
    TVDB est plus court que les episodes locaux. C'est ce cas qui
    declenche le fallback dans la route accept.
    """
    filename = f"The.Big.C.S04E{ep_num:02d}.mkv"
    vf = VideoFile(path=f"/downloads/{filename}", filename=filename)
    candidates: list[dict] = []
    if include_target_tvdb:
        candidates.append(
            {
                "id": str(TVDB_ID),
                "title": "The Big C",
                "year": 2010,
                "score": 95.0,
                "source": "tvdb",
            }
        )
    # Candidats "faux positifs" type The Big Bake, scores faibles
    candidates.append(
        {
            "id": "99999",
            "title": "The Big Bake",
            "year": 2019,
            "score": 75.0,
            "source": "tvdb",
        }
    )
    return PendingValidation(
        id=f"p{ep_num}",
        video_file=vf,
        candidates=candidates,
        validation_status=ValidationStatus.PENDING,
    )


def _make_group(pendings: list[PendingValidation]) -> ExcessEpisodeGroup:
    return ExcessEpisodeGroup(
        tvdb_id=TVDB_ID,
        series_title="The Big C",
        series_year=2010,
        season_number=SEASON,
        tvdb_count=4,
        pendings=pendings,
        validated_seasons_count=3,
    )


@pytest.fixture
def validation_service():
    svc = MagicMock()
    svc.validate_candidate = AsyncMock(return_value=SimpleNamespace(title="The Big C"))
    svc.reject_pending = MagicMock()
    return svc


@pytest.fixture
def container(session, validation_service):
    c = MagicMock()
    c.validation_service = MagicMock(return_value=validation_service)
    pending_repo = MagicMock()
    pending_repo._session = session
    c.pending_validation_repository = MagicMock(return_value=pending_repo)
    return c


@pytest.fixture
def client_with_group(container):
    """Crée un client FastAPI minimal avec un groupe d'anomalies en etat."""
    app = FastAPI()
    app.include_router(workflow_router)
    app.state.container = container

    progress = WorkflowProgress()
    progress.anomaly_groups = [_make_group([_make_pending(n) for n in (5, 6, 7, 8)])]
    app.state.workflow_progress = progress

    return TestClient(app), progress


def test_accept_creates_override_and_validates(
    client_with_group, session, validation_service
):
    """POST accept → SeasonOverrideModel persiste + pendings valides.

    Scenario reel : les pendings n'ont PAS la serie cible TVDB dans
    leurs candidats (filter_by_episode_count l'a eliminee). La route
    doit fabriquer un SearchResult fallback et valider quand meme.
    """
    client, progress = client_with_group

    response = client.post(
        "/workflow/anomalies/accept",
        data={"tvdb_id": TVDB_ID, "season": SEASON},
    )

    assert response.status_code == 200

    # Override persisté avec episode_count = max(8, tvdb_count=4) = 8
    override = session.exec(
        select(SeasonOverrideModel).where(
            SeasonOverrideModel.tvdb_id == TVDB_ID,
            SeasonOverrideModel.season_number == SEASON,
        )
    ).first()
    assert override is not None
    assert override.episode_count == 8

    # validate_candidate appele pour chaque pending
    assert validation_service.validate_candidate.await_count == 4

    # Le candidat passe a validate_candidate est bien celui du groupe
    # (fabrique depuis les infos du groupe puisque pending.candidates
    # ne contient que "The Big Bake").
    first_call = validation_service.validate_candidate.await_args_list[0]
    passed_candidate = first_call.args[1]
    assert str(passed_candidate.id) == str(TVDB_ID)
    assert passed_candidate.source == "tvdb"
    assert passed_candidate.title == "The Big C"

    # Groupe retire de l'etat
    assert progress.anomaly_groups == []


def test_accept_max_episode_count(container, session, validation_service):
    """Groupe E05..E08 → override.episode_count = 8."""
    app = FastAPI()
    app.include_router(workflow_router)
    app.state.container = container
    progress = WorkflowProgress()
    progress.anomaly_groups = [_make_group([_make_pending(n) for n in (5, 6, 7, 8)])]
    app.state.workflow_progress = progress
    client = TestClient(app)

    client.post(
        "/workflow/anomalies/accept",
        data={"tvdb_id": TVDB_ID, "season": SEASON},
    )

    override = session.exec(
        select(SeasonOverrideModel).where(
            SeasonOverrideModel.tvdb_id == TVDB_ID,
            SeasonOverrideModel.season_number == SEASON,
        )
    ).first()
    assert override is not None
    assert override.episode_count == 8  # max(5,6,7,8)


def test_dismiss_noop(client_with_group, session, validation_service):
    """POST dismiss → rien en base, groupe retire de la session."""
    client, progress = client_with_group

    response = client.post(
        "/workflow/anomalies/dismiss",
        data={"tvdb_id": TVDB_ID, "season": SEASON},
    )

    assert response.status_code == 200
    # Aucun override cree
    assert (
        session.exec(select(SeasonOverrideModel)).first() is None
    )
    # Ni validate_candidate, ni reject_pending
    validation_service.validate_candidate.assert_not_awaited()
    validation_service.reject_pending.assert_not_called()
    # Groupe retire
    assert progress.anomaly_groups == []


def test_trash_removes_pendings(client_with_group, session, validation_service):
    """POST trash → reject_pending appele sur chaque pending."""
    client, progress = client_with_group

    response = client.post(
        "/workflow/anomalies/trash",
        data={"tvdb_id": TVDB_ID, "season": SEASON},
    )

    assert response.status_code == 200
    # reject_pending appele 4 fois
    assert validation_service.reject_pending.call_count == 4
    # Pas d'override cree
    assert session.exec(select(SeasonOverrideModel)).first() is None
    # Groupe retire
    assert progress.anomaly_groups == []
