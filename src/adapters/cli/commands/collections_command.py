"""Commandes CLI ``cineorg collections`` (phase courts-métrages P4).

Sous-app Typer exposant :

* ``collections list`` — liste les collections locales + nombre de films.
* ``collections suggest`` — propose des collections à partir des courts
  orphelins (préfixe de titre commun). Mode dry-run par défaut.
* ``collections suggest --apply`` — crée les collections suggérées et
  rattache les films. Un ``cineorg reclassify-shorts`` doit ensuite être
  lancé pour déplacer les symlinks vers le nouveau dossier de franchise.
"""

from typing import Annotated

import typer
from rich.prompt import Confirm
from rich.table import Table

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.container import Container
from src.core.entities.local_collection import LocalCollection
from src.infrastructure.persistence.repositories.local_collection_repository import (
    SQLModelLocalCollectionRepository,
)
from src.services.local_collection_suggester import LocalCollectionSuggester


collections_app = typer.Typer(
    name="collections",
    help="Collections locales (regroupement de courts-métrages)",
    rich_markup_mode="rich",
)


@collections_app.command("list")
def list_collections() -> None:
    """Liste les collections locales avec leur nombre de films."""
    container = Container()
    container.database.init()

    from src.infrastructure.persistence.database import get_session

    session = next(get_session())
    repo = SQLModelLocalCollectionRepository(session)

    with suppress_loguru():
        console.print("\n[bold cyan]Collections locales[/bold cyan]\n")
        counts = repo.list_with_movie_counts()
        if not counts:
            console.print(
                "[dim]Aucune collection locale définie pour l'instant.[/dim]\n"
                "[dim]Utiliser [bold]cineorg collections suggest[/bold] "
                "pour en proposer.[/dim]"
            )
            return

        table = Table(
            title=f"{len(counts)} collection(s) locale(s)",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Nom", style="white")
        table.add_column("Films", justify="right", style="green")
        table.add_column("Description", style="dim", overflow="fold")
        for entry in counts:
            table.add_row(
                str(entry.collection.id),
                entry.collection.name,
                str(entry.movie_count),
                entry.collection.description or "",
            )
        console.print(table)


@collections_app.command("suggest")
def suggest_collections(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Afficher les suggestions sans les créer (défaut : actif)",
        ),
    ] = True,
) -> None:
    """Propose des collections à partir des courts orphelins (préfixe commun)."""
    container = Container()
    container.database.init()

    from src.infrastructure.persistence.database import get_session

    session = next(get_session())
    suggester = LocalCollectionSuggester(session)
    repo = SQLModelLocalCollectionRepository(session)

    with suppress_loguru():
        console.print("\n[bold cyan]Suggestions de collections locales[/bold cyan]\n")
        groups = suggester.find_orphan_groups()
        if not groups:
            console.print(
                "[green]Aucun regroupement à suggérer "
                "(courts orphelins isolés ou tous déjà classés).[/green]\n"
            )
            return

        table = Table(
            title=f"{len(groups)} suggestion(s)",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Nom suggéré", style="magenta")
        table.add_column("Films", justify="right", style="green")
        table.add_column("Exemples", style="dim", overflow="fold")
        for group in groups:
            sample_titles = ", ".join(m.title for m in group.movies[:3])
            if len(group.movies) > 3:
                sample_titles += ", …"
            table.add_row(
                group.suggested_name,
                str(len(group.movies)),
                sample_titles,
            )
        console.print(table)

        if dry_run:
            console.print("\n[yellow]Mode dry-run : aucune collection créée.[/yellow]")
            console.print(
                "[dim]Relancer avec --no-dry-run pour créer les collections "
                "et rattacher les films.[/dim]"
            )
            return

        if not Confirm.ask(
            f"\n[bold]Créer ces {len(groups)} collection(s) "
            f"et rattacher les films ?[/bold]",
            default=False,
        ):
            console.print("[yellow]Création annulée.[/yellow]")
            return

        console.print("\n[bold]Création...[/bold]\n")
        created = 0
        attached = 0
        for group in groups:
            existing = repo.get_by_name(group.suggested_name)
            if existing is None:
                collection = repo.save(LocalCollection(name=group.suggested_name))
                created += 1
            else:
                collection = existing
            for movie in group.movies:
                movie.local_collection_id = collection.id
                session.add(movie)
                attached += 1
            session.commit()
            console.print(
                f"  [green]✓[/green] {collection.name} "
                f"({len(group.movies)} film(s) rattaché(s))"
            )

        console.print(
            f"\n[bold green]Terminé.[/bold green] "
            f"{created} collection(s) créée(s), {attached} film(s) rattaché(s)."
        )
        console.print(
            "\n[dim]Lancer [bold]cineorg reclassify-shorts --no-dry-run[/bold] "
            "pour déplacer les symlinks vers les nouveaux dossiers de franchise.[/dim]"
        )
