"""Tests pour la commande CLI `migrate-nas review`."""

from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from src.adapters.cli.commands.migrate_nas_command import migrate_nas_app
from src.adapters.cli.commands.migrate_nas_command.review import render_review_card
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.decisions import DecisionStatus
from src.services.migration.plan_builder import serialize_plan
from src.services.migration.state_store import MigrationStateStore


def test_review_command_help():
    """`migrate-nas review --help` doit afficher l'usage sans erreur."""
    runner = CliRunner()
    result = runner.invoke(migrate_nas_app, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout.lower()
    assert "--bucket" in result.stdout
    assert "--resume" in result.stdout


def test_review_command_runs_no_pending(tmp_path):
    """La loop s'exécute sans lever d'exception pour un plan vide (0 items)."""
    from src.services.migration.plan_builder import serialize_plan

    plan_obj = MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=[],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan_obj))
    runner = CliRunner()
    result = runner.invoke(migrate_nas_app, ["review", str(plan_path)])
    assert result.exit_code == 0
    assert "Aucun item" in result.output


def test_review_command_invalid_bucket_returns_usage_error(tmp_path):
    """`--bucket foo` doit produire une erreur Typer claire, pas un traceback."""
    runner = CliRunner()
    plan = tmp_path / "plan.json"
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan), "--bucket", "foo"],
    )
    assert result.exit_code != 0
    # typer.BadParameter writes the message to stderr (mix_stderr default true)
    # so it lands in result.output / result.stdout
    assert "Bucket invalide" in result.output or "Bucket invalide" in result.stderr


def _nv_item() -> MigrationItem:
    return MigrationItem(
        item_id="nv1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Wrong.mkv"),
        source_path=Path("/old/Wrong.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1_500_000_000,
        rating=RatingDecision(),
        match=MatchInfo(
            top_candidates=[
                {
                    "title": "Wrong",
                    "year": 2012,
                    "score": 67.0,
                    "source": "tmdb",
                    "tmdb_id": 83186,
                },
                {
                    "title": "Détour mortel",
                    "year": 2003,
                    "score": 44.67,
                    "source": "tmdb",
                    "tmdb_id": 9902,
                },
            ]
        ),
        is_symlink_source=False,
    )


def test_render_review_card_needs_validation_shows_top_candidates():
    """render_review_card affiche les candidats TMDB pour un item needs_validation."""
    item = _nv_item()
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_review_card(console, item, position=(42, 140))
    out = buf.getvalue()
    assert "Wrong.mkv" in out
    assert "Wrong" in out and "2012" in out
    assert "67" in out  # score top
    assert "Détour mortel" in out
    assert "42/140" in out  # position
    assert "needs_validation" in out


def test_render_review_card_low_rated_formats_rating_one_decimal():
    """LOW_RATED : la note est formatée à 1 décimale, ou '?' si None."""
    from src.services.migration.dataclasses import RatingDecision

    def _make(rating_value):
        return MigrationItem(
            item_id="lr1",
            bucket=Bucket.LOW_RATED,
            symlink_path=Path("/old/MovieX.mkv"),
            source_path=Path("/old/MovieX.mkv"),
            destination_path=None,
            media_root="Films",
            relative_category="",
            size_bytes=10_000,
            rating=RatingDecision(value=rating_value),
            match=MatchInfo(),
            is_symlink_source=False,
        )

    # Note présente : formatée à 1 décimale
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_review_card(console, _make(5.7345), position=(1, 1))
    out = buf.getvalue()
    assert "Note 5.7" in out
    assert "< seuil" in out

    # Note None : tombé sur "?"
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_review_card(console, _make(None), position=(1, 1))
    out = buf.getvalue()
    assert "Note ?" in out


# ---------------------------------------------------------------------------
# Tests de la loop interactive (Task 9)
# ---------------------------------------------------------------------------


def _write_plan_with_nv(tmp_path):
    """Crée un plan minimal avec 1 item needs_validation, retourne paths."""
    item = _nv_item()
    plan = MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    return plan_path, item


def test_review_loop_accept_top_persists_decision(tmp_path):
    """User tape 'a' → décision approved avec match du top candidate."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",  # accept top
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision is not None
    assert decision.decision == DecisionStatus.APPROVED
    assert decision.chosen_tmdb_id == 83186  # top candidate id
    assert decision.chosen_score == 67.0
    store.close()


def test_review_loop_pick_candidate_by_number(tmp_path):
    """User tape '2' → décision approved avec match du 2e candidate."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="2\n",
    )
    assert result.exit_code == 0
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision.chosen_tmdb_id == 9902  # 2e candidate (Détour mortel)
    store.close()


def test_review_loop_skip_persists_skipped(tmp_path):
    """User tape 'k' → décision SKIPPED persistée."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="k\n",
    )
    store = MigrationStateStore(state_path)
    assert store.get_decision(item.item_id).decision == DecisionStatus.SKIPPED
    store.close()


def test_review_loop_quit_stops_iteration(tmp_path):
    """Avec 2 items, taper 'q' au 1er ne décide rien."""
    items = [_nv_item(), _nv_item()]
    items[1] = MigrationItem(
        item_id="nv2",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Other.mkv"),
        source_path=Path("/old/Other.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(top_candidates=[]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="q\n",
    )
    store = MigrationStateStore(state_path)
    assert store.get_decision("nv1") is None
    assert store.get_decision("nv2") is None
    store.close()


def test_review_command_closes_store_when_build_service_fails(tmp_path, monkeypatch):
    """Si Container() raise, le store déjà ouvert doit être fermé proprement."""
    from src.adapters.cli.commands.migrate_nas_command import review as review_module

    plan_path, _ = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"

    # Force _build_review_service à raise après que store a été instancié
    def boom(plan_path, store):
        raise RuntimeError("container HS")

    monkeypatch.setattr(review_module, "_build_review_service", boom)

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
    )
    # L'erreur remonte, mais le store doit avoir été créé puis fermé sans fuite.
    assert result.exit_code != 0
    # Vérifie qu'on peut ré-ouvrir le store immédiatement (preuve qu'il a été
    # fermé : sinon la connexion serait verrouillée — sqlite tolère mais le
    # test sert surtout de smoke pour le chemin finally).
    store = MigrationStateStore(state_path)
    store.close()
