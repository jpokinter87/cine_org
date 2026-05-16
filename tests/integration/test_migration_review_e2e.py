"""
Test e2e MVP : plan synthétique → review CLI scriptée → apply.

Scénario : 1 item NEEDS_VALIDATION → l'utilisateur tape 'a' (accept top) dans
la review CLI → la décision APPROVED est persistée dans le state store SQLite →
apply hydrate l'item (match.tmdb_id) et le transfère via FakeRsync.

Prouve que la boucle complète plan→review→apply fonctionne de bout en bout
(MVP phase 44.6).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.adapters.cli.commands.migrate_nas_command import migrate_nas_app, run_apply
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
    TransferStatus,
)
from src.services.migration.decisions import DecisionStatus
from src.services.migration.plan_builder import serialize_plan
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.transfer_executor import RsyncResult


# ---------------------------------------------------------------------------
# FakeRsync : copie réelle du fichier pour satisfaire le verify_hash
# ---------------------------------------------------------------------------


class _FakeRsync:
    """Simule rsync en copiant physiquement source → destination."""

    def run(
        self,
        source: Path,
        destination: Path,
        on_progress=None,
    ) -> RsyncResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return RsyncResult(success=True)


# ---------------------------------------------------------------------------
# Test principal
# ---------------------------------------------------------------------------


def test_plan_to_review_to_apply_flow(tmp_path: Path) -> None:
    """Smoke test : 1 item NV → review accept top → apply le transfère."""
    # -----------------------------------------------------------------
    # Préparation : fichier source physique (mode raw)
    # -----------------------------------------------------------------
    src = tmp_path / "old" / "movie.mkv"
    src.parent.mkdir()
    src.write_bytes(b"FAKE_MOVIE_CONTENT" * 1000)

    item = MigrationItem(
        item_id="e2e1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=src,
        source_path=src,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=src.stat().st_size,
        rating=RatingDecision(),
        match=MatchInfo(
            top_candidates=[
                {
                    "title": "Avatar",
                    "year": 2009,
                    "score": 95.0,
                    "tmdb_id": 19995,
                    "source": "tmdb",
                }
            ]
        ),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1,
        source_root=tmp_path / "old",
        destination_root=tmp_path / "new",
        threshold=6.0,
        stats=MigrationStats(),
        items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "plan.json.state.sqlite"

    # -----------------------------------------------------------------
    # Étape 1 : review CLI en mode "accept top" (input = "a\n")
    # -----------------------------------------------------------------
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",
    )
    assert result.exit_code == 0, (
        f"review CLI a échoué (exit_code={result.exit_code}):\n{result.output}"
    )

    # -----------------------------------------------------------------
    # Vérification : décision APPROVED persistée avec chosen_tmdb_id
    # -----------------------------------------------------------------
    store = MigrationStateStore(state_path)
    decision = store.get_decision("e2e1")
    assert decision is not None, "Aucune décision persistée pour e2e1"
    assert decision.decision == DecisionStatus.APPROVED
    assert decision.chosen_tmdb_id == 19995
    store.close()

    # -----------------------------------------------------------------
    # Étape 2 : apply
    # Seul _build_raw_finalizer est mocké (évite le wiring Container /
    # clés API / DB CineOrg). Le FakeRawFinalizer retourne un chemin de
    # destination fixe ; _FakeRsync copie réellement le fichier source.
    # -----------------------------------------------------------------
    dest_path = tmp_path / "new" / "Avatar.mkv"

    fake_finalizer = MagicMock()
    fake_finalizer.prepare = MagicMock(return_value=dest_path)
    fake_finalizer.finalize = MagicMock()

    with patch(
        "src.adapters.cli.commands.migrate_nas_command.orchestrators._build_raw_finalizer",
        return_value=fake_finalizer,
    ):
        outcomes = run_apply(
            plan_path=plan_path,
            state_store_path=state_path,
            rsync_runner=_FakeRsync(),
        )

    # -----------------------------------------------------------------
    # Vérifications finales
    # -----------------------------------------------------------------
    assert len(outcomes) == 1, f"Attendu 1 outcome, obtenu {len(outcomes)}"
    assert outcomes[0].status == TransferStatus.COMMITTED, (
        f"Statut inattendu : {outcomes[0].status} "
        f"(message : {outcomes[0].error_message})"
    )

    # prepare doit avoir été appelé exactement une fois
    fake_finalizer.prepare.assert_called_once()

    # L'item passé à prepare doit avoir match.tmdb_id hydraté depuis la décision
    item_passed = fake_finalizer.prepare.call_args.args[0]
    assert item_passed.match.tmdb_id == 19995, (
        f"tmdb_id non hydraté : {item_passed.match.tmdb_id}"
    )
