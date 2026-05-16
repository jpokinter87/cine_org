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
    RatingDecision,
)


def test_review_command_help():
    """`migrate-nas review --help` doit afficher l'usage sans erreur."""
    runner = CliRunner()
    result = runner.invoke(migrate_nas_app, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout.lower()
    assert "--bucket" in result.stdout
    assert "--resume" in result.stdout


def test_review_command_runs_stub(tmp_path):
    """Le stub s'exécute sans lever d'exception pour un plan inexistant.

    Le stub ne lit pas encore le plan (Task 9 le fera) — il imprime juste
    la ligne de statut et le message stub. Donc un path arbitraire suffit.
    """
    runner = CliRunner()
    plan = tmp_path / "plan.json"
    result = runner.invoke(migrate_nas_app, ["review", str(plan)])
    assert result.exit_code == 0
    assert "Pas encore implémenté" in result.stdout


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
