"""Commande CLI ``cineorg check-missing-files``.

Scanne ``MovieModel`` et ``EpisodeModel`` à la recherche de fiches dont le
``file_path`` ne pointe plus sur un fichier existant. Trois actions ensuite,
combinables :

* ``--resolve`` : pour chaque fiche orpheline, cherche le même basename
  ailleurs dans ``storage_dir`` et ``video_dir`` (fichier déplacé) et
  affiche les candidats dans le tableau.
* ``--repair``  : ``--resolve`` + applique automatiquement le seul candidat
  trouvé (réécriture du ``file_path`` en DB ; le filesystem n'est pas touché).
* ``--prune``   : envoie en corbeille les fiches qu'on ne sait pas réparer
  (réversible via ``/maintenance/trash``).
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm
from rich.table import Table

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.container import Container
from src.services.missing_file_resolver import MissingFileResolver
from src.services.missing_files_scanner import MissingFilesScanner, MissingRecord


def check_missing_files(
    resolve: Annotated[
        bool,
        typer.Option(
            "--resolve",
            help=(
                "Chercher chaque fiche orpheline ailleurs (basename) et "
                "afficher les candidats trouvés"
            ),
        ),
    ] = False,
    repair: Annotated[
        bool,
        typer.Option(
            "--repair",
            help=(
                "Comme --resolve, et réécrit file_path en DB quand un seul "
                "candidat est trouvé (aucune modif filesystem)"
            ),
        ),
    ] = False,
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help="Envoyer en corbeille les fiches dont le fichier est manquant",
        ),
    ] = False,
) -> None:
    """Liste les fiches DB pointant vers un fichier qui n'existe plus."""
    container = Container()
    container.database.init()
    settings = container.config()

    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    # --repair implique la résolution
    resolve = resolve or repair

    with suppress_loguru():
        console.print(
            "\n[bold cyan]Scan des fiches sans fichier physique[/bold cyan]\n"
        )

        scanner = MissingFilesScanner(session)
        total = scanner.count_to_scan()

        if total == 0:
            console.print("[green]Aucune fiche avec file_path à vérifier.[/green]\n")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[label]}[/dim]"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            scan_task = progress.add_task(
                "Vérification filesystem…", total=total, label=""
            )

            def _on_progress(current: int, _total: int, label: str) -> None:
                short = label[:60] + "…" if len(label) > 60 else label
                progress.update(scan_task, completed=current, label=short)

            records = scanner.find_missing(on_progress=_on_progress)

        if not records:
            console.print(
                "[green]Aucune fiche orpheline.[/green] "
                "Toutes les entrées DB pointent vers un fichier existant.\n"
            )
            return

        # Résolution par basename (storage + video)
        candidates_by_record: dict[int, list[Path]] = {}
        if resolve:
            search_dirs = [
                d
                for d in (settings.storage_dir, settings.video_dir)
                if d and Path(d).exists()
            ]
            resolver = MissingFileResolver(search_dirs=search_dirs)
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            ) as progress:
                resolve_task = progress.add_task(
                    "Recherche basename dans storage + video…",
                    total=len(records),
                )
                for idx, rec in enumerate(records, start=1):
                    candidates_by_record[idx] = resolver.find_candidates(rec)
                    progress.update(resolve_task, completed=idx)

        # Affichage tabulaire (avec colonne candidat si --resolve)
        table = Table(
            title=f"{len(records)} fiche(s) sans fichier",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Type", style="dim", no_wrap=True)
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Titre", style="white")
        table.add_column("Chemin attendu", style="red dim", overflow="fold")
        if resolve:
            table.add_column("Candidat trouvé", style="green", overflow="fold")
        for idx, rec in enumerate(records, start=1):
            row = [
                rec.entity_type,
                str(rec.entity_id),
                rec.title,
                rec.file_path,
            ]
            if resolve:
                cands = candidates_by_record.get(idx, [])
                if not cands:
                    row.append("[dim]—[/dim]")
                elif len(cands) == 1:
                    row.append(str(cands[0]))
                else:
                    row.append(
                        f"[yellow]{len(cands)} candidats[/yellow] : "
                        + " ; ".join(str(c) for c in cands)
                    )
            table.add_row(*row)
        console.print(table)

        # --repair : applique les réparations sans confirmation par item
        if repair:
            repaired = 0
            ambiguous = 0
            for idx, rec in enumerate(records, start=1):
                cands = candidates_by_record.get(idx, [])
                if len(cands) == 1:
                    resolver_instance = MissingFileResolver(
                        search_dirs=[]
                    )  # apply_repair n'a pas besoin de l'index
                    if resolver_instance.apply_repair(session, rec, cands[0]):
                        repaired += 1
                elif len(cands) > 1:
                    ambiguous += 1
            console.print(
                f"\n[bold green]Réparation : {repaired} fiche(s) recâblée(s).[/bold green]"
            )
            if ambiguous:
                console.print(
                    f"[yellow]{ambiguous} fiche(s) ambiguë(s) "
                    f"(plusieurs candidats) — à traiter manuellement.[/yellow]"
                )
            unresolved = len(records) - repaired
            if unresolved and prune:
                # Recalcule la liste après réparation pour ne purger que les vraiment manquants
                remaining = MissingFilesScanner(session).find_missing()
                _do_prune(scanner, remaining)
            elif unresolved:
                console.print(
                    f"\n[dim]{unresolved} fiche(s) toujours sans fichier. "
                    "Relancer avec --prune pour les envoyer en corbeille.[/dim]"
                )
            return

        if not prune:
            console.print("\n[yellow]Mode dry-run : aucune fiche supprimée.[/yellow]")
            hint = (
                "[dim]Relancer avec --repair pour réécrire le file_path quand un "
                "candidat est trouvé, ou --prune pour envoyer en corbeille."
            )
            if not resolve:
                hint += " --resolve seul affiche les candidats sans toucher à la DB."
            hint += "[/dim]"
            console.print(hint)
            return

        _do_prune(scanner, records)


def _do_prune(scanner: MissingFilesScanner, records: list[MissingRecord]) -> None:
    if not records:
        return
    if not Confirm.ask(
        f"\n[bold]Envoyer ces {len(records)} fiche(s) en corbeille ?[/bold]",
        default=False,
    ):
        console.print("[yellow]Pruning annulé.[/yellow]")
        return
    pruned = scanner.prune(records)
    console.print(
        f"\n[bold green]Terminé.[/bold green] "
        f"{pruned} fiche(s) envoyée(s) en corbeille."
    )
    console.print(
        "[dim]Restauration possible via /maintenance/trash si nécessaire.[/dim]"
    )
