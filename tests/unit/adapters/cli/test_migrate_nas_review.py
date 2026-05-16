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
