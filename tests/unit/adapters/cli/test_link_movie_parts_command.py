"""La commande link-movie-parts est exposee et applique le linker."""


def test_commande_importable():
    from src.adapters.cli.commands import link_movie_parts

    assert callable(link_movie_parts)


def test_commande_enregistree_dans_app():
    from src.main import app

    names = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
    assert "link-movie-parts" in names
