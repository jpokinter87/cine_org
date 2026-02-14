"""
Affichage du batch de transferts et gestion des conflits.

Fournit les fonctions d'affichage du resume des transferts (arborescence),
la gestion des conflits de contenu similaire, et l'execution du batch.
"""

from typing import TYPE_CHECKING

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from src.services.transferer import (
        ExistingFileInfo,
        SimilarContentInfo,
        TransferResult,
    )


class ConflictResolution(str):
    """Options de resolution de conflit."""

    KEEP_OLD = "old"
    KEEP_NEW = "new"
    KEEP_BOTH = "both"
    SKIP = "skip"


def format_file_size(size_bytes: int) -> str:
    """Formate une taille en octets en format lisible."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} Go"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f} Mo"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} Ko"
    return f"{size_bytes} o"


def display_similar_content_conflict(
    similar_info: "SimilarContentInfo",
    new_file_info: "ExistingFileInfo | None",
    new_file_count: int = 1,
) -> None:
    """
    Affiche un conflit de contenu similaire pour decision utilisateur.

    Args:
        similar_info: Information sur le contenu similaire existant
        new_file_info: Information sur le nouveau fichier (si disponible)
        new_file_count: Nombre de nouveaux fichiers (pour les series)
    """
    from . import console

    console.print("\n[bold yellow]⚠ Contenu similaire detecte[/bold yellow]\n")
    console.print(f"[dim]{similar_info.similarity_reason}[/dim]\n")

    # Tableau comparatif
    table = Table(
        title="Comparaison", show_header=True, header_style="bold cyan"
    )
    table.add_column("", style="dim")
    table.add_column(f"[red]Existant[/red]\n{similar_info.existing_title}", justify="center")
    table.add_column(f"[green]Nouveau[/green]\n{similar_info.new_title}", justify="center")

    # Collecter les infos existantes
    existing_files = similar_info.existing_files
    total_existing_size = sum(f.size_bytes for f in existing_files)
    existing_resolutions = set(f.resolution for f in existing_files if f.resolution)
    existing_codecs = set(f.video_codec for f in existing_files if f.video_codec)
    existing_audio = set(f.audio_codec for f in existing_files if f.audio_codec)

    # Infos du nouveau fichier
    new_size = format_file_size(new_file_info.size_bytes) if new_file_info else "?"
    new_resolution = new_file_info.resolution if new_file_info else "?"
    new_video_codec = new_file_info.video_codec if new_file_info else "?"
    new_audio_codec = new_file_info.audio_codec if new_file_info else "?"

    # Ajouter les lignes
    table.add_row(
        "Fichiers",
        str(len(existing_files)),
        str(new_file_count),
    )
    table.add_row(
        "Taille totale",
        format_file_size(total_existing_size),
        new_size,
    )
    table.add_row(
        "Resolution",
        ", ".join(sorted(existing_resolutions)) or "?",
        new_resolution or "?",
    )
    table.add_row(
        "Codec video",
        ", ".join(sorted(existing_codecs)) or "?",
        new_video_codec or "?",
    )
    table.add_row(
        "Codec audio",
        ", ".join(sorted(existing_audio)) or "?",
        new_audio_codec or "?",
    )

    console.print(table)


def prompt_conflict_resolution() -> str:
    """
    Demande a l'utilisateur de choisir la resolution du conflit.

    Returns:
        "old", "new", "both" ou "skip"
    """
    from . import console

    console.print("\n[bold]Options:[/bold]")
    console.print("  [cyan]1[/cyan] Garder l'[red]ancien[/red] (deplacer le nouveau vers la zone d'attente)")
    console.print("  [cyan]2[/cyan] Garder le [green]nouveau[/green] (deplacer l'ancien vers la zone d'attente)")
    console.print("  [cyan]3[/cyan] Garder les [yellow]deux[/yellow] (creer un sous-dossier pour le nouveau)")
    console.print("  [cyan]s[/cyan] Passer (ne rien faire pour ce fichier)")

    choice = Prompt.ask(
        "[bold]Choix[/bold]",
        choices=["1", "2", "3", "s"],
        default="s",
    )

    if choice == "1":
        return ConflictResolution.KEEP_OLD
    elif choice == "2":
        return ConflictResolution.KEEP_NEW
    elif choice == "3":
        return ConflictResolution.KEEP_BOTH
    else:
        return ConflictResolution.SKIP


def display_batch_summary(transfers: list[dict]) -> None:
    """
    Affiche un resume des transferts prevus sous forme d'arborescence.

    Structure affichee:
    - Zone symlinks (video_dir)
      - Films ou Series groupes par type/lettre/titre
        - Fichier symlink -> [dim]cible stockage[/dim]

    Args:
        transfers: Liste de dicts avec keys 'source', 'destination', 'new_filename',
                   'symlink_destination', 'is_series', 'title', 'year'
    """
    from . import console

    if not transfers:
        console.print("[yellow]Aucun transfert a effectuer.[/yellow]")
        return

    # Extraire video_dir et storage_dir depuis les chemins
    first_symlink = transfers[0].get("symlink_destination")
    first_storage = transfers[0].get("destination")

    # Determiner les racines
    video_dir = None
    storage_dir = None
    if first_symlink:
        # Remonter pour trouver la racine video (avant Films/ ou Séries/)
        parts = first_symlink.parts
        for i, part in enumerate(parts):
            if part in ("Films", "Séries"):
                video_dir = first_symlink.parents[len(parts) - i - 1]
                break
    if first_storage:
        parts = first_storage.parts
        for i, part in enumerate(parts):
            if part in ("Films", "Séries"):
                storage_dir = first_storage.parents[len(parts) - i - 1]
                break

    # Separer films et series
    movies = [t for t in transfers if not t.get("is_series", False)]
    series = [t for t in transfers if t.get("is_series", False)]

    # Arbre principal (zone symlinks)
    tree = Tree(f"[bold blue]{video_dir or 'Symlinks'}[/bold blue]")

    # Branche Films
    if movies:
        films_branch = tree.add("[bold cyan]Films/[/bold cyan]")
        # Grouper par sous-repertoire (genre/lettre)
        movie_dirs: dict[str, list[dict]] = {}
        for m in movies:
            symlink_dest = m.get("symlink_destination")
            if symlink_dest and video_dir:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    # Prendre le chemin parent sans "Films/"
                    parent_parts = rel_path.parts[1:-1]  # Enlever Films/ et le fichier
                    parent = "/".join(parent_parts) if parent_parts else ""
                except ValueError:
                    parent = ""
            else:
                parent = ""
            if parent not in movie_dirs:
                movie_dirs[parent] = []
            movie_dirs[parent].append(m)

        for dir_path in sorted(movie_dirs.keys()):
            if dir_path:
                dir_branch = films_branch.add(f"[cyan]{dir_path}/[/cyan]")
            else:
                dir_branch = films_branch
            for m in movie_dirs[dir_path]:
                new_name = m["new_filename"]
                storage_dest = m.get("destination")
                if storage_dest and storage_dir:
                    try:
                        rel_storage = storage_dest.relative_to(storage_dir)
                        storage_str = f" [dim]-> {rel_storage}[/dim]"
                    except ValueError:
                        storage_str = f" [dim]-> {storage_dest}[/dim]"
                else:
                    storage_str = ""
                dir_branch.add(f"[green]{new_name}[/green]{storage_str}")

    # Branche Series
    if series:
        # Grouper par type, lettre, serie, saison
        type_groups: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}

        for s in series:
            symlink_dest = s.get("symlink_destination")
            series_type = "Séries TV"
            letter = "?"

            if symlink_dest and video_dir:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    parts = rel_path.parts
                    # Structure: Séries/{Type}/{Lettre}/{Titre}/{Saison}/fichier
                    if len(parts) >= 5:
                        series_type = parts[1]
                        letter = parts[2]
                except ValueError:
                    pass

            title = s.get("title", "Inconnu")
            year = s.get("year", "")
            series_key = f"{title} ({year})" if year else title
            season_dir = symlink_dest.parent.name if symlink_dest else "Saison ??"

            if series_type not in type_groups:
                type_groups[series_type] = {}
            if letter not in type_groups[series_type]:
                type_groups[series_type][letter] = {}
            if series_key not in type_groups[series_type][letter]:
                type_groups[series_type][letter][series_key] = {}
            if season_dir not in type_groups[series_type][letter][series_key]:
                type_groups[series_type][letter][series_key][season_dir] = []
            type_groups[series_type][letter][series_key][season_dir].append(s)

        # Afficher l'arbre des series
        for series_type in sorted(type_groups.keys()):
            type_branch = tree.add(f"[bold magenta]Séries/{series_type}/[/bold magenta]")

            for letter in sorted(type_groups[series_type].keys()):
                letter_branch = type_branch.add(f"[magenta]{letter}/[/magenta]")

                for series_name in sorted(type_groups[series_type][letter].keys()):
                    series_branch = letter_branch.add(f"[magenta]{series_name}/[/magenta]")

                    for season in sorted(type_groups[series_type][letter][series_name].keys()):
                        season_branch = series_branch.add(f"[dim]{season}/[/dim]")
                        episodes = type_groups[series_type][letter][series_name][season]
                        episodes.sort(key=lambda e: e["new_filename"])

                        for ep in episodes:
                            new_name = ep["new_filename"]
                            storage_dest = ep.get("destination")
                            if storage_dest and storage_dir:
                                try:
                                    rel_storage = storage_dest.relative_to(storage_dir)
                                    storage_str = f" [dim]-> {rel_storage}[/dim]"
                                except ValueError:
                                    storage_str = f" [dim]-> {storage_dest}[/dim]"
                            else:
                                storage_str = ""
                            season_branch.add(f"[green]{new_name}[/green]{storage_str}")

    console.print(tree)


async def execute_batch_transfer(
    transfers: list[dict], transferer
) -> list[dict]:
    """
    Execute les transferts avec barre de progression.

    Signature transferer.transfer_file(source, destination, create_symlink=True) -> TransferResult

    Args:
        transfers: Liste de dicts avec keys 'source', 'destination'
        transferer: TransfererService injecte

    Returns:
        Liste de dicts {'success': bool, 'filename': str, 'error': str | None}
    """
    from . import console

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Transfert...", total=len(transfers))

        for transfer in transfers:
            source = transfer["source"]
            destination = transfer["destination"]
            filename = source.name if hasattr(source, "name") else str(source)

            progress.update(task, description=f"[cyan]{filename}[/cyan]")

            # Appel transferer.transfer_file(source, destination, create_symlink=True)
            # Retourne TransferResult avec .success, .error, .conflict
            symlink_dest = transfer.get("symlink_destination")
            result: "TransferResult" = transferer.transfer_file(
                source=source,
                destination=destination,
                create_symlink=True,
                symlink_destination=symlink_dest,
            )

            if result.success:
                results.append({"success": True, "filename": filename, "error": None})
            else:
                error_msg = result.error or (
                    str(result.conflict) if result.conflict else "Erreur inconnue"
                )
                results.append({"success": False, "filename": filename, "error": error_msg})

            progress.advance(task)

    return results
