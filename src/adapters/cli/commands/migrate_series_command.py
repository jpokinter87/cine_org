"""
Commande CLI migrate-series : migre la structure des repertoires series.

Renomme les repertoires (Séries→Series, Séries TV→TV), met a jour les
file_path en base de donnees, et reconstruit les symlinks.
Supporte le mode dry-run et la reclassification automatique par genre.
"""

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from sqlalchemy import text

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.container import Container


# Mapping des renommages de repertoires (ancien → nouveau)
_DIR_RENAMES = [
    # Sous-repertoire d'abord (avant de renommer le parent)
    ("Séries TV", "TV"),
]
_ROOT_RENAMES = [
    ("Séries", "Series"),
]

# Remplacements DB (ordre : plus specifique d'abord)
_DB_REPLACEMENTS = [
    ("/Séries TV/", "/TV/"),
    ("/Séries/", "/Series/"),
]


def migrate_series(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Afficher le plan sans executer"),
    ] = True,
    reclassify: Annotated[
        bool,
        typer.Option(
            "--reclassify", help="Reclassifier animation/mangas/documentaires par genre"
        ),
    ] = False,
) -> None:
    """Migre la structure des repertoires series (Séries→Series, Séries TV→TV)."""
    container = Container()
    container.database.init()
    config = container.config()
    storage_dir = config.storage_dir
    video_dir = config.video_dir

    with suppress_loguru():
        console.print("\n[bold cyan]Migration des repertoires series[/bold cyan]\n")

        # Phase 1 : Analyser les renommages de repertoires
        dir_ops = _plan_directory_renames(storage_dir, video_dir)

        # Phase 2 : Analyser les mises a jour DB
        from src.infrastructure.persistence.database import get_session

        session = next(get_session())
        db_ops = _plan_db_updates(session)

        # Phase 3 : Analyser la reclassification (si demandee)
        reclass_ops = []
        if reclassify:
            reclass_ops = _plan_reclassification(session, storage_dir, video_dir)

        # Afficher le plan
        _display_plan(dir_ops, db_ops, reclass_ops, dry_run)

        if dry_run:
            console.print(
                "\n[yellow]Mode dry-run : aucune modification effectuee.[/yellow]"
            )
            console.print(
                "[dim]Relancer avec --no-dry-run pour executer la migration.[/dim]"
            )
            return

        # Confirmation
        if not Confirm.ask("\n[bold]Executer la migration ?[/bold]", default=False):
            console.print("[yellow]Migration annulee.[/yellow]")
            return

        # Execution
        console.print("\n[bold]Execution de la migration...[/bold]\n")

        # Etape 1 : Renommer les repertoires
        renamed = _execute_directory_renames(dir_ops)
        console.print(f"  Repertoires renommes : [green]{renamed}[/green]")

        # Etape 2 : Mettre a jour la DB
        updated = _execute_db_updates(session)
        console.print(f"  Chemins DB mis a jour : [green]{updated}[/green]")

        # Etape 3 : Reconstruire les symlinks casses
        repaired = _repair_broken_symlinks(video_dir, storage_dir)
        console.print(f"  Symlinks repares : [green]{repaired}[/green]")

        # Etape 4 : Reclassification (adapter les chemins post-migration)
        reclassed = 0
        if reclassify and reclass_ops:
            for op in reclass_ops:
                for old_pat, new_pat in _DB_REPLACEMENTS:
                    op["old_path"] = op["old_path"].replace(old_pat, new_pat)
                    op["new_path"] = op["new_path"].replace(old_pat, new_pat)
            reclassed = _execute_reclassification(
                reclass_ops, session, video_dir, storage_dir
            )
            console.print(f"  Series reclassifiees : [green]{reclassed}[/green]")

        session.commit()

        console.print("\n[bold green]Migration terminee.[/bold green]")
        console.print(
            f"  {renamed} dirs, {updated} chemins DB, "
            f"{repaired} symlinks, {reclassed} reclassifications"
        )


def _plan_directory_renames(
    storage_dir: Path, video_dir: Path
) -> list[tuple[Path, Path]]:
    """Planifie les renommages de repertoires (ancien → nouveau)."""
    ops = []

    for base_dir in [storage_dir, video_dir]:
        old_root = base_dir / "Séries"
        if not old_root.exists():
            continue

        # Sous-repertoires d'abord
        for old_name, new_name in _DIR_RENAMES:
            old_sub = old_root / old_name
            if old_sub.exists():
                new_sub = old_root / new_name
                if not new_sub.exists():
                    ops.append((old_sub, new_sub))

        # Puis la racine
        new_root = base_dir / "Series"
        if not new_root.exists():
            ops.append((old_root, new_root))

    return ops


def _plan_db_updates(session) -> dict[str, int]:
    """Compte les lignes a mettre a jour par table/colonne."""
    counts = {}

    for old, new in _DB_REPLACEMENTS:
        for table, column in [
            ("episodes", "file_path"),
            ("video_files", "path"),
            ("video_files", "symlink_path"),
        ]:
            key = f"{table}.{column} [{old}→{new}]"
            result = session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE :pattern"),
                {"pattern": f"%{old}%"},
            )
            count = result.scalar() or 0
            if count > 0:
                counts[key] = count

    return counts


def _plan_reclassification(session, storage_dir: Path, video_dir: Path) -> list[dict]:
    """
    Identifie les series a reclassifier par genre.

    Cherche les series Animation/Anime/Documentaire actuellement sous TV/
    et calcule leur destination correcte.
    """
    ops = []

    # Charger les series avec genres
    series_list = session.execute(
        text(
            "SELECT id, title, year, genres_json FROM series WHERE genres_json IS NOT NULL"
        )
    ).fetchall()

    for row in series_list:
        series_id, title, year, genres_json = row
        if not genres_json:
            continue

        genres = json.loads(genres_json)
        genres_lower = [g.lower() for g in genres]

        # Determiner le type attendu
        if "anime" in genres_lower:
            expected_type = "Mangas"
        elif "animation" in genres_lower:
            expected_type = "Animation"
        elif "documentaire" in genres_lower:
            expected_type = "Series documentaires"
        else:
            continue  # Deja TV, rien a faire

        # Chercher les episodes de cette serie
        episodes = session.execute(
            text(
                "SELECT file_path FROM episodes WHERE series_id = :sid AND file_path IS NOT NULL"
            ),
            {"sid": series_id},
        ).fetchall()

        for (ep_path_str,) in episodes:
            ep_path = Path(ep_path_str)
            # Verifier si l'episode est sous le mauvais type (TV)
            # Apres migration, le chemin sera .../Series/TV/...
            path_str = str(ep_path)
            if "/TV/" not in path_str and "/Séries TV/" not in path_str:
                continue

            # Calculer la nouvelle destination
            # Remplacer /Series/TV/ ou /Séries/Séries TV/ par le bon type
            if expected_type == "Series documentaires":
                new_path_str = path_str.replace(
                    "/Series/TV/", "/Documentaires/Series documentaires/"
                ).replace("/Séries/Séries TV/", "/Documentaires/Series documentaires/")
            else:
                new_path_str = path_str.replace(
                    "/Series/TV/", f"/Series/{expected_type}/"
                ).replace("/Séries/Séries TV/", f"/Series/{expected_type}/")

            if new_path_str != path_str:
                ops.append(
                    {
                        "series_title": title,
                        "series_year": year,
                        "expected_type": expected_type,
                        "old_path": ep_path_str,
                        "new_path": new_path_str,
                    }
                )

    return ops


def _display_plan(
    dir_ops: list[tuple[Path, Path]],
    db_ops: dict[str, int],
    reclass_ops: list[dict],
    dry_run: bool,
) -> None:
    """Affiche le plan de migration."""
    mode = "[yellow]DRY-RUN[/yellow]" if dry_run else "[red]EXECUTION[/red]"
    console.print(f"Mode : {mode}\n")

    # Renommages de repertoires
    if dir_ops:
        # Calculer les chemins finaux (appliquer tous les renommages successifs)
        all_renames = {str(o): str(n) for o, n in dir_ops}
        table = Table(title="Renommages de repertoires", show_header=True)
        table.add_column("Ancien", style="red")
        table.add_column("Final", style="green")
        for old, new in dir_ops:
            # Appliquer les renommages parents au chemin final
            final = str(new)
            for rename_old, rename_new in all_renames.items():
                if rename_old != str(old) and final.startswith(rename_old):
                    final = rename_new + final[len(rename_old):]
            table.add_row(str(old), final)
        console.print(table)
    else:
        console.print("[dim]Aucun repertoire a renommer (deja migre).[/dim]")

    # Mises a jour DB
    if db_ops:
        table = Table(title="Mises a jour DB", show_header=True)
        table.add_column("Table.colonne [remplacement]", style="cyan")
        table.add_column("Lignes", justify="right", style="yellow")
        for key, count in db_ops.items():
            table.add_row(Text(key), str(count))
        console.print(table)
    else:
        console.print("[dim]Aucun chemin DB a mettre a jour.[/dim]")

    # Reclassification
    if reclass_ops:
        # Grouper par serie
        by_series: dict[str, tuple[str, int]] = {}
        for op in reclass_ops:
            key = f"{op['series_title']} ({op['series_year']})"
            if key not in by_series:
                by_series[key] = (op["expected_type"], 0)
            t, c = by_series[key]
            by_series[key] = (t, c + 1)

        table = Table(title="Reclassification par genre", show_header=True)
        table.add_column("Serie", style="magenta")
        table.add_column("Nouveau type", style="green")
        table.add_column("Episodes", justify="right", style="yellow")
        for series_name, (etype, count) in sorted(by_series.items()):
            table.add_row(series_name, etype, str(count))
        console.print(table)


def _execute_directory_renames(dir_ops: list[tuple[Path, Path]]) -> int:
    """Execute les renommages de repertoires."""
    count = 0
    for old, new in dir_ops:
        if old.exists() and not new.exists():
            # Creer le parent si necessaire
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            count += 1
    return count


def _execute_db_updates(session) -> int:
    """Execute les mises a jour des chemins en DB."""
    total = 0

    for old, new in _DB_REPLACEMENTS:
        for table, column in [
            ("episodes", "file_path"),
            ("video_files", "path"),
            ("video_files", "symlink_path"),
        ]:
            result = session.execute(
                text(
                    f"UPDATE {table} SET {column} = REPLACE({column}, :old, :new) "
                    f"WHERE {column} LIKE :pattern"
                ),
                {"old": old, "new": new, "pattern": f"%{old}%"},
            )
            total += result.rowcount

    return total


def _repair_broken_symlinks(video_dir: Path, storage_dir: Path) -> int:
    """Reconstruit les symlinks casses apres renommage des repertoires."""
    count = 0
    series_dir = video_dir / "Series"
    if not series_dir.exists():
        return 0

    # Aussi scanner Documentaires/ pour les series documentaires
    scan_dirs = [series_dir]
    doc_dir = video_dir / "Documentaires"
    if doc_dir.exists():
        scan_dirs.append(doc_dir)

    for scan_dir in scan_dirs:
        for link in scan_dir.rglob("*"):
            if not link.is_symlink():
                continue

            try:
                target = link.resolve()
                if target.exists():
                    continue  # Symlink valide
            except OSError:
                pass

            # Symlink casse — essayer de corriger la cible
            try:
                old_target = link.readlink()
            except OSError:
                continue

            old_target_str = str(old_target)
            new_target_str = old_target_str
            for old, new in _DB_REPLACEMENTS:
                new_target_str = new_target_str.replace(old, new)

            if new_target_str != old_target_str:
                new_target = Path(new_target_str)
                if new_target.exists():
                    link.unlink()
                    link.symlink_to(new_target)
                    count += 1

    return count


def _execute_reclassification(
    reclass_ops: list[dict],
    session,
    video_dir: Path,
    storage_dir: Path,
) -> int:
    """Execute la reclassification des series par genre."""
    count = 0
    storage_prefix = str(storage_dir)
    video_prefix = str(video_dir)

    for op in reclass_ops:
        old_path = Path(op["old_path"])
        new_path = Path(op["new_path"])

        if not old_path.exists():
            continue
        if new_path.exists():
            continue

        # Creer le repertoire destination
        new_path.parent.mkdir(parents=True, exist_ok=True)

        # Deplacer le fichier physique
        shutil.move(str(old_path), str(new_path))

        # Mettre a jour le file_path en DB
        session.execute(
            text("UPDATE episodes SET file_path = :new WHERE file_path = :old"),
            {"new": str(new_path), "old": op["old_path"]},
        )
        session.execute(
            text("UPDATE video_files SET path = :new WHERE path = :old"),
            {"new": str(new_path), "old": op["old_path"]},
        )

        # Mettre a jour le symlink correspondant
        # Calculer le chemin symlink en remplacant storage_dir par video_dir
        old_symlink_str = op["old_path"].replace(storage_prefix, video_prefix, 1)
        new_symlink_str = op["new_path"].replace(storage_prefix, video_prefix, 1)
        old_symlink = Path(old_symlink_str)
        new_symlink = Path(new_symlink_str)

        if old_symlink.is_symlink():
            old_symlink.unlink()
        if not new_symlink.exists():
            new_symlink.parent.mkdir(parents=True, exist_ok=True)
            new_symlink.symlink_to(new_path)

        # Mettre a jour symlink_path en DB
        session.execute(
            text(
                "UPDATE video_files SET symlink_path = :new WHERE symlink_path = :old"
            ),
            {"new": new_symlink_str, "old": old_symlink_str},
        )

        count += 1

    return count
