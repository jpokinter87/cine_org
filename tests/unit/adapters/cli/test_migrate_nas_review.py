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


def test_review_loop_search_replaces_candidates(tmp_path, monkeypatch):
    """User tape 's' → prompt "Wrong Turn" → search live → choisir nouveau candidat."""
    from src.core.ports.api_clients import SearchResult
    from src.services.migration.state_store import MigrationStateStore

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"

    # Patch ReviewService.search_tmdb pour retourner un nouveau candidat
    new_results = [
        SearchResult(id="9902", title="Détour mortel", year=2003,
                     score=98.0, source="tmdb"),
    ]

    async def fake_search(*args, **kwargs):
        return new_results

    monkeypatch.setattr(
        "src.services.migration.review_service.MigrationReviewService.search_tmdb",
        fake_search,
    )

    runner = CliRunner()
    # Inputs : 's' → "Wrong Turn" → '1' (choisir 1er résultat search)
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="s\nWrong Turn\n1\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision.chosen_tmdb_id == 9902
    assert decision.chosen_title == "Détour mortel"
    store.close()


def test_render_review_card_unrated_shows_plan_time_match():
    """UNRATED : la carte affiche le match plan pour que l'utilisateur sache ce qu'il valide."""
    item = MigrationItem(
        item_id="u_card",
        bucket=Bucket.UNRATED,
        symlink_path=Path("/old/Foo.mkv"),
        source_path=Path("/old/Foo.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(
            tmdb_id=12345,
            score=88.0,
            top_candidates=[
                {"title": "Some Film", "year": 2020, "score": 88.0,
                 "tmdb_id": 12345, "source": "tmdb"},
            ],
        ),
        is_symlink_source=False,
    )
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_review_card(console, item, position=(1, 1))
    out = buf.getvalue()
    assert "Note absente" in out
    assert "Match plan" in out
    assert "Some Film" in out
    assert "2020" in out
    assert "88" in out  # score


def test_review_loop_unrated_migrate_anyway(tmp_path):
    """unrated + 'm' → décision APPROVED avec match déjà connu."""
    item = MigrationItem(
        item_id="u1",
        bucket=Bucket.UNRATED,
        symlink_path=Path("/old/Untitled.mkv"),
        source_path=Path("/old/Untitled.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(
            tmdb_id=12345,
            score=88.0,
            top_candidates=[
                {
                    "title": "Some film",
                    "year": 2020,
                    "score": 88.0,
                    "tmdb_id": 12345,
                    "source": "tmdb",
                }
            ],
        ),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1,
        source_root=Path("/s"),
        destination_root=Path("/d"),
        threshold=6.0,
        stats=MigrationStats(),
        items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="m\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("u1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.chosen_tmdb_id == 12345  # repris du match existant
    store.close()


def test_review_loop_unrated_keep_skip_persists_skipped(tmp_path):
    """unrated + 'k' → décision SKIPPED."""
    from src.services.migration.dataclasses import (
        MigrationPlan,
        MigrationStats,
    )
    from src.services.migration.plan_builder import serialize_plan

    item = MigrationItem(
        item_id="u_skip",
        bucket=Bucket.UNRATED,
        symlink_path=Path("/old/X.mkv"),
        source_path=Path("/old/X.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="k\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("u_skip")
    assert d.decision == DecisionStatus.SKIPPED
    store.close()


def test_review_loop_low_rated_delete_source_after(tmp_path):
    """low_rated + 'd' → APPROVED + delete_source_after=True."""
    item = MigrationItem(
        item_id="lr1",
        bucket=Bucket.LOW_RATED,
        symlink_path=Path("/old/Bad.mkv"),
        source_path=Path("/old/Bad.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(value=3.5, source="imdb"),
        match=MatchInfo(tmdb_id=99, top_candidates=[
            {"title": "Bad", "year": 2010, "score": 100.0, "tmdb_id": 99,
             "source": "tmdb"}
        ]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    # 'd' → "Confirmer suppression source ? > y"
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="d\ny\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("lr1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.delete_source_after is True
    store.close()


def test_review_loop_low_rated_migrate_anyway_no_delete(tmp_path):
    """low_rated + 'm' → APPROVED + delete_source_after=False (pas de suppression)."""
    item = MigrationItem(
        item_id="lr_m",
        bucket=Bucket.LOW_RATED,
        symlink_path=Path("/old/MigrateAnyway.mkv"),
        source_path=Path("/old/MigrateAnyway.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(value=4.0, source="imdb"),
        match=MatchInfo(
            tmdb_id=42,
            score=92.0,
            top_candidates=[
                {"title": "Mediocre Movie", "year": 2015, "score": 92.0,
                 "tmdb_id": 42, "source": "tmdb"}
            ],
        ),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="m\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("lr_m")
    assert d.decision == DecisionStatus.APPROVED
    assert d.chosen_tmdb_id == 42
    assert d.delete_source_after is False
    store.close()


def test_review_loop_low_rated_delete_then_cancel_then_skip(tmp_path):
    """low_rated + 'd' + 'n' (annule) → carte redessinée → 'k' (skip).

    Garantit que le garde-fou Confirm.ask refuse bien la destruction quand
    l'utilisateur tape 'n', et que le redraw permet ensuite de choisir 'k'.
    """
    item = MigrationItem(
        item_id="lr_cancel",
        bucket=Bucket.LOW_RATED,
        symlink_path=Path("/old/Cancel.mkv"),
        source_path=Path("/old/Cancel.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(value=2.0, source="imdb"),
        match=MatchInfo(
            tmdb_id=7,
            score=88.0,
            top_candidates=[
                {"title": "Awful", "year": 2018, "score": 88.0,
                 "tmdb_id": 7, "source": "tmdb"}
            ],
        ),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    # 'd' → Confirm prompt → 'n' (annule) → redraw → 'k' (skip)
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="d\nn\nk\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("lr_cancel")
    # Après annulation puis skip : décision SKIPPED, pas APPROVED
    assert d.decision == DecisionStatus.SKIPPED
    assert d.delete_source_after is False
    store.close()


def test_review_loop_already_in_library_keep_dest(tmp_path):
    """already_in_library + 'k' → APPROVED + duplicate_action=keep_dest."""
    from src.services.migration.decisions import DuplicateAction

    src_file = tmp_path / "src.mkv"
    src_file.write_bytes(b"\x00" * 1024)
    dest_file = tmp_path / "dst.mkv"
    dest_file.write_bytes(b"\x00" * 2048)

    item = MigrationItem(
        item_id="ail1",
        bucket=Bucket.ALREADY_IN_LIBRARY,
        symlink_path=src_file,
        source_path=src_file,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1024,
        rating=RatingDecision(),
        match=MatchInfo(tmdb_id=42),
        is_symlink_source=False,
        tags=[f"existing:{dest_file}"],
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="k\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("ail1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.duplicate_action == DuplicateAction.KEEP_DEST
    store.close()


def test_review_loop_already_in_library_accept_reco_new_replaces_dest(
    tmp_path, monkeypatch
):
    """already_in_library + 'a' avec reco='new' → APPROVED + duplicate_action=REPLACE_DEST."""
    from src.services.migration.decisions import DuplicateAction
    from src.services.duplicate_detector import QualityComparison

    src_file = tmp_path / "src.mkv"
    src_file.write_bytes(b"\x00" * 1024)
    dest_file = tmp_path / "dst.mkv"
    dest_file.write_bytes(b"\x00" * 2048)

    item = MigrationItem(
        item_id="ail_a_new",
        bucket=Bucket.ALREADY_IN_LIBRARY,
        symlink_path=src_file,
        source_path=src_file,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1024,
        rating=RatingDecision(),
        match=MatchInfo(tmdb_id=42),
        is_symlink_source=False,
        tags=[f"existing:{dest_file}"],
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    # Force la reco à "new" (source NAS gagne) → l'action 'a' doit donner REPLACE_DEST
    def fake_reco(self, item):
        return QualityComparison(
            existing_score=70.0,
            new_score=92.0,
            recommended="new",
            existing_breakdown={},
            new_breakdown={},
        )

    monkeypatch.setattr(
        "src.services.migration.review_service.MigrationReviewService.duplicate_recommendation",
        fake_reco,
    )

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("ail_a_new")
    assert d.decision == DecisionStatus.APPROVED
    assert d.duplicate_action == DuplicateAction.REPLACE_DEST
    store.close()


def test_review_loop_already_in_library_accept_reco_unavailable_redraws(
    tmp_path, monkeypatch
):
    """already_in_library + 'a' alors que la reco a échoué → redraw (pas de décision)."""
    src_file = tmp_path / "src.mkv"
    src_file.write_bytes(b"\x00" * 1024)
    dest_file = tmp_path / "dst.mkv"
    dest_file.write_bytes(b"\x00" * 2048)

    item = MigrationItem(
        item_id="ail_a_none",
        bucket=Bucket.ALREADY_IN_LIBRARY,
        symlink_path=src_file,
        source_path=src_file,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1024,
        rating=RatingDecision(),
        match=MatchInfo(tmdb_id=42),
        is_symlink_source=False,
        tags=[f"existing:{dest_file}"],
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    # Force la reco à lever → reco=None côté handler
    def boom(self, item):
        raise RuntimeError("mediainfo HS")

    monkeypatch.setattr(
        "src.services.migration.review_service.MigrationReviewService.duplicate_recommendation",
        boom,
    )

    runner = CliRunner()
    # 'a' → reco=None → redraw → 'k' (skip vers KEEP_DEST pour terminer proprement)
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\nk\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("ail_a_none")
    # Après redraw + k : décision APPROVED avec KEEP_DEST
    from src.services.migration.decisions import DuplicateAction
    assert d.decision == DecisionStatus.APPROVED
    assert d.duplicate_action == DuplicateAction.KEEP_DEST
    store.close()


def test_review_loop_defer_to_web(tmp_path):
    """User tape 'w' → décision DEFERRED_TO_WEB."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="w\n",
    )
    assert result.exit_code == 0
    store = MigrationStateStore(state_path)
    d = store.get_decision(item.item_id)
    assert d.decision == DecisionStatus.DEFERRED_TO_WEB
    store.close()
