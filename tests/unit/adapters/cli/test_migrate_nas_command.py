"""
Tests pour la commande CLI `migrate-nas` (sous-commandes plan / apply / status).

On teste les helpers internes (`build_plan`, `run_apply`, `run_status`) qui
encapsulent la logique métier et permettent d'injecter un FakeRsync /
session in-memory sans dépendre du Container ni d'une vraie base.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.cli.commands.migrate_nas_command import (
    build_plan,
    run_apply,
    run_status,
)
from src.infrastructure.persistence.models import MovieModel
from src.services.migration.dataclasses import (
    Bucket,
    TransferStatus,
)
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.transfer_executor import RsyncResult


# ---- Fakes ---------------------------------------------------------------


@dataclass
class _Behavior:
    success: bool
    error: Optional[str] = None
    on_success: Optional[Callable[[Path, Path], None]] = None


class FakeRsync:
    def __init__(self, behaviors: list[_Behavior]) -> None:
        self.calls: list[tuple[Path, Path]] = []
        self._behaviors = list(behaviors)

    def run(
        self,
        source: Path,
        destination: Path,
        on_progress=None,
    ) -> RsyncResult:
        self.calls.append((source, destination))
        b = self._behaviors.pop(0)
        if b.success and b.on_success:
            b.on_success(source, destination)
        return RsyncResult(success=b.success, error=b.error)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


# ---- Fixtures -----------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def layout(tmp_path):
    """Arborescence : un film en DB (Avatar) + un film hors DB (Inconnu)."""
    old_storage = tmp_path / "old_storage"
    source_root = tmp_path / "old_video" / "Films" / "Drame" / "A"
    destination_storage = tmp_path / "new_storage"
    destination_video = tmp_path / "new_video"
    old_storage.mkdir(parents=True)
    source_root.mkdir(parents=True)
    destination_storage.mkdir(parents=True)
    destination_video.mkdir(parents=True)

    # Avatar : présent en DB avec note 8.0
    avatar_target = old_storage / "Avatar (2009) FR x265 1080p.mkv"
    avatar_target.write_bytes(b"AVATAR" * 100)
    (source_root / "Avatar (2009) FR x265 1080p.mkv").symlink_to(avatar_target)

    # Inconnu : pas en DB → bucket UNRATED
    inconnu_target = old_storage / "Inconnu (2050) FR x265 1080p.mkv"
    inconnu_target.write_bytes(b"INCONNU" * 100)
    (source_root / "Inconnu (2050) FR x265 1080p.mkv").symlink_to(inconnu_target)

    return {
        "source_root": tmp_path / "old_video",
        "destination_storage": destination_storage,
        "destination_video": destination_video,
        "avatar_target": avatar_target,
        "avatar_symlink": source_root / "Avatar (2009) FR x265 1080p.mkv",
    }


@pytest.fixture
def db_with_avatar(session):
    movie = MovieModel(tmdb_id=10, title="Avatar", year=2009, imdb_rating=7.5)
    movie.genres = ["Science-Fiction"]
    session.add(movie)
    session.commit()
    return session


# ---- build_plan ---------------------------------------------------------


def test_build_plan_writes_json_and_csvs(layout, db_with_avatar, tmp_path):
    output = tmp_path / "plan.json"
    csv_dir = tmp_path / "review"

    plan = build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=output,
        csv_dir=csv_dir,
        session=db_with_avatar,
    )

    # Plan JSON présent et parseable
    assert output.exists()
    payload = output.read_text(encoding="utf-8")
    obj = json.loads(payload)
    assert obj["threshold"] == 6.0
    assert obj["stats"]["total_symlinks"] == 2

    # CSV de revue créés
    assert (csv_dir / "low_rated.csv").exists()
    assert (csv_dir / "unrated.csv").exists()
    assert (csv_dir / "broken.csv").exists()

    # Plan retourné cohérent
    assert plan.stats.to_migrate == 1  # Avatar
    assert plan.stats.unrated == 1  # Inconnu
    migrate_items = [it for it in plan.items if it.bucket == Bucket.MIGRATE]
    assert len(migrate_items) == 1
    assert "Avatar" in migrate_items[0].symlink_path.name


def test_build_plan_without_csv_dir_skips_csvs(layout, db_with_avatar, tmp_path):
    output = tmp_path / "plan.json"

    build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=output,
        csv_dir=None,
        session=db_with_avatar,
    )

    assert output.exists()
    # Aucun CSV créé puisqu'on n'a pas de répertoire
    assert not (tmp_path / "low_rated.csv").exists()


# ---- run_apply ----------------------------------------------------------


def test_run_apply_executes_pending_items(layout, db_with_avatar, tmp_path):
    plan_path = tmp_path / "plan.json"
    state_path = tmp_path / "state.sqlite"

    build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=plan_path,
        csv_dir=None,
        session=db_with_avatar,
    )

    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    outcomes = run_apply(
        plan_path=plan_path,
        state_store_path=state_path,
        rsync_runner=rsync,
    )

    assert len(outcomes) == 1
    assert outcomes[0].status == TransferStatus.COMMITTED
    assert layout["avatar_symlink"].is_symlink()
    # Le symlink pointe maintenant vers la nouvelle destination
    assert str(layout["destination_storage"]) in str(
        layout["avatar_symlink"].resolve()
    )


def test_run_apply_is_idempotent_after_completion(layout, db_with_avatar, tmp_path):
    plan_path = tmp_path / "plan.json"
    state_path = tmp_path / "state.sqlite"

    build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=plan_path,
        csv_dir=None,
        session=db_with_avatar,
    )

    rsync1 = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    run_apply(plan_path=plan_path, state_store_path=state_path, rsync_runner=rsync1)

    # Second run : tout est COMMITTED, aucun rsync ne doit être appelé
    rsync2 = FakeRsync([])
    outcomes = run_apply(
        plan_path=plan_path, state_store_path=state_path, rsync_runner=rsync2
    )

    assert outcomes == []
    assert rsync2.calls == []


# ---- run_status ---------------------------------------------------------


def test_run_status_aggregates_by_bucket_and_transfer_status(
    layout, db_with_avatar, tmp_path
):
    plan_path = tmp_path / "plan.json"
    state_path = tmp_path / "state.sqlite"

    build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=plan_path,
        csv_dir=None,
        session=db_with_avatar,
    )

    # Pré-remplit le state store avec un item COMMITTED
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    store = MigrationStateStore(state_path)
    store.init_from_plan(plan)
    migrate_id = next(
        it.item_id for it in plan.items if it.bucket == Bucket.MIGRATE
    )
    store.update_status(migrate_id, TransferStatus.COMMITTED)
    store.close()

    summary = run_status(plan_path=plan_path, state_store_path=state_path)

    # Stats du plan (par bucket)
    assert summary["plan"]["total"] == 2
    assert summary["plan"]["migrate"] == 1
    assert summary["plan"]["unrated"] == 1
    # Avancement (par TransferStatus)
    assert summary["progress"]["committed"] == 1
    # Pas de pending (le seul MIGRATE est COMMITTED)
    assert summary["progress"].get("pending", 0) == 0


def test_run_status_without_state_store_reports_plan_only(
    layout, db_with_avatar, tmp_path
):
    plan_path = tmp_path / "plan.json"
    build_plan(
        source_root=layout["source_root"],
        destination_storage_dir=layout["destination_storage"],
        destination_video_dir=layout["destination_video"],
        threshold=6.0,
        output_path=plan_path,
        csv_dir=None,
        session=db_with_avatar,
    )

    # state_store_path inexistant : status doit quand même afficher le plan
    summary = run_status(
        plan_path=plan_path,
        state_store_path=tmp_path / "absent.sqlite",
    )

    assert summary["plan"]["total"] == 2
    # Aucune ligne dans le state store → progress vide
    assert summary["progress"] == {}
