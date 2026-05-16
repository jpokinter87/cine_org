"""Tests pour la commande CLI `migrate-nas review`."""

from typer.testing import CliRunner

from src.adapters.cli.commands.migrate_nas_command import migrate_nas_app


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
