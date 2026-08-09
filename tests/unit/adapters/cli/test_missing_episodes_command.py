"""La commande missing-episodes est exposée et refuse les formats inconnus."""

import pytest
import typer


def test_commande_importable():
    from src.adapters.cli.commands import missing_episodes

    assert callable(missing_episodes)


def test_commande_enregistree_dans_app():
    from src.main import app

    names = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
    assert "missing-episodes" in names


def test_format_inconnu_sort_en_erreur():
    """Un format non supporté échoue avant toute lecture de la base."""
    from src.adapters.cli.commands import missing_episodes

    with pytest.raises(typer.Exit) as exc:
        missing_episodes(output_format="json")
    assert exc.value.exit_code == 1
