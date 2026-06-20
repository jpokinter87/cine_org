"""Commande CLI link-movie-parts : rattache les parties orphelines de films.

Scanne la zone video a la recherche de symlinks « … Partie N … » (N >= 2) dont
le film (Partie 1) existe en base, et cree les lignes MoviePart manquantes.
Dry-run par defaut ; --apply pour ecrire. Le storage n'est jamais modifie.
"""

from pathlib import Path
from typing import Annotated

import typer

from src.adapters.cli.validation import console
from src.container import Container
from src.services.movie_parts import MoviePartLinker


def link_movie_parts(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Exécuter (défaut : dry-run, rapport seul)"),
    ] = False,
) -> None:
    """Rattache les parties orphelines (Partie ≥ 2) des films multi-parties.

    Sans --apply : affiche le plan (rien n'est écrit).
    Avec --apply : crée les lignes MoviePart manquantes en base.
    """
    from loguru import logger as loguru_logger

    container = Container()
    config = container.config()
    container.database.init()

    loguru_logger.disable("src")
    session = container.session()
    try:
        linker = MoviePartLinker(session, Path(config.video_dir))
        with console.status("[cyan]Analyse de la zone video..."):
            plan = linker.build_plan()

        if not plan:
            console.print("\n[green]Aucune partie orpheline à rattacher.[/green]")
            return

        for link in plan:
            console.print(
                f"  [cyan]Partie {link.part_number}[/cyan] → film #{link.movie_id} : "
                f"{Path(link.symlink_path).name}"
            )

        if not apply:
            console.print(
                f"\n[bold]Dry-run :[/bold] {len(plan)} partie(s) à rattacher."
            )
            console.print("[dim]Pour exécuter : cineorg link-movie-parts --apply[/dim]")
        else:
            created = linker.apply(plan)
            console.print(
                f"\n[bold green]{created}[/bold green] partie(s) rattachée(s)."
            )
    finally:
        session.close()
