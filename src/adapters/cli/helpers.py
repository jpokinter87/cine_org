"""
Utilitaires partages pour les commandes CLI de CineOrg.

Ce module fournit :
- suppress_loguru : context manager pour desactiver/reactiver les logs loguru
- with_container : decorateur injectant un container initialise
- async_command : decorateur transformant une fonction async en commande sync
- console : instance Rich Console partagee (reexportee depuis validation)
- _extract_series_info : extraction saison/episode d'un nom de fichier
- _extract_language_from_filename : extraction de la langue d'un nom de fichier
- _get_series_folder : repertoire parent d'un fichier en attente
- _display_transfer_tree : affichage arborescent des transferts prevus
"""

import asyncio
import inspect
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Optional

from loguru import logger as loguru_logger

from src.container import Container

# Re-export console depuis validation pour que tous les modules puissent l'importer ici
from src.adapters.cli.validation import console


@contextmanager
def suppress_loguru():
    """
    Context manager pour desactiver les logs loguru pendant l'affichage Rich.

    Usage:
        with suppress_loguru():
            console.print(...)
    """
    loguru_logger.disable("src")
    try:
        yield
    finally:
        loguru_logger.enable("src")


def with_container(requires_db: bool = True):
    """
    Decorateur qui injecte un container initialise en premier argument.

    Args:
        requires_db: Si True (defaut), initialise la base de donnees.

    Usage:
        @with_container()
        async def my_command(container, ...):
            config = container.config()
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            container = Container()
            if requires_db:
                container.database.init()
            return await func(container, *args, **kwargs)
        return wrapper
    return decorator


def async_command(func):
    """
    Transforme une fonction async en commande sync via asyncio.run().

    Preserve les annotations Typer pour que les options/arguments soient
    correctement interpretes.

    Usage:
        @async_command
        @with_container()
        async def my_command(container, ...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        asyncio.run(func(*args, **kwargs))
    # Preserver les annotations Typer
    wrapper.__signature__ = inspect.signature(func)
    wrapper.__annotations__ = func.__annotations__
    return wrapper


def _extract_series_info(filename: str) -> tuple[int, int]:
    """
    Extrait le numero de saison et d'episode d'un nom de fichier.

    Utilise le parser guessit pour extraire les informations de serie.
    Le titre d'episode sera recupere depuis TVDB.

    Args:
        filename: Nom du fichier video

    Returns:
        Tuple (season_number, episode_number), defaut (1, 1) si non trouve
    """
    from src.adapters.parsing.guessit_parser import GuessitFilenameParser
    from src.core.value_objects.parsed_info import MediaType

    parser = GuessitFilenameParser()
    parsed = parser.parse(filename, MediaType.SERIES)

    season = parsed.season if parsed.season else 1
    episode = parsed.episode if parsed.episode else 1

    return season, episode


def _extract_language_from_filename(filename: str) -> Optional[str]:
    """
    Extrait la langue du nom de fichier via guessit.

    Utilise comme fallback quand mediainfo ne detecte pas la langue
    des pistes audio (fichiers sans tag de langue).

    Args:
        filename: Nom du fichier video

    Returns:
        Code langue en majuscules (ex: "FR", "EN"), ou None si non trouve
    """
    from src.adapters.parsing.guessit_parser import GuessitFilenameParser

    parser = GuessitFilenameParser()
    parsed = parser.parse(filename)

    return parsed.language  # Deja en majuscules ou None


def _get_series_folder(pend) -> Optional[Path]:
    """
    Retourne le repertoire parent d'un fichier en attente de validation.

    Les episodes d'une meme serie sont generalement dans le meme repertoire.
    Utilise pour regrouper et auto-valider les episodes apres validation du premier.

    Args:
        pend: PendingValidation avec video_file

    Returns:
        Path du repertoire parent ou None si non disponible
    """
    if pend.video_file and pend.video_file.path:
        return pend.video_file.path.parent
    return None


def _display_transfer_tree(
    transfers: list[dict], storage_dir: Path, video_dir: Path
) -> None:
    """
    Affiche l'arborescence des transferts prevus en mode dry-run.

    Organise les transferts par type (Films/Series) puis par repertoire
    pour une visualisation claire de la structure de destination (symlinks).

    Args:
        transfers: Liste des transferts avec source, destination, symlink_destination, etc.
        storage_dir: Repertoire de stockage racine (fichiers physiques)
        video_dir: Repertoire video racine (symlinks)
    """
    from rich.tree import Tree

    # Separer films et series
    movies = [t for t in transfers if not t.get("is_series", False)]
    series = [t for t in transfers if t.get("is_series", False)]

    # Arbre principal (affiche la structure des symlinks dans video_dir)
    tree = Tree(f"[bold blue]{video_dir}[/bold blue]")

    # Branche Films (structure des symlinks avec genres et subdivisions)
    if movies:
        films_branch = tree.add("[bold cyan]Films/[/bold cyan]")
        # Grouper par sous-repertoire relatif (depuis symlink_destination ou destination)
        movie_dirs: dict[str, list[dict]] = {}
        for m in movies:
            # Utiliser symlink_destination pour l'affichage (structure video avec genres)
            dest = m.get("symlink_destination") or m["destination"]
            # Chemin relatif depuis video_dir ou storage_dir
            try:
                rel_path = dest.relative_to(video_dir)
                parent = str(rel_path.parent)
            except ValueError:
                try:
                    rel_path = dest.relative_to(storage_dir)
                    parent = str(rel_path.parent)
                except ValueError:
                    parent = str(dest.parent)
            if parent not in movie_dirs:
                movie_dirs[parent] = []
            movie_dirs[parent].append(m)

        for dir_path in sorted(movie_dirs.keys()):
            dir_branch = films_branch.add(f"[cyan]{dir_path}/[/cyan]")
            for m in movie_dirs[dir_path]:
                source_name = m["source"].name if m["source"] else "?"
                new_name = m["new_filename"]
                dir_branch.add(f"[dim]{source_name}[/dim] -> [green]{new_name}[/green]")

    # Branche Series (structure avec type: Series TV / Animation / Mangas)
    if series:
        # Grouper par type de serie, lettre, puis par serie, puis par saison
        # Structure: {type: {lettre: {serie: {saison: [episodes]}}}}
        type_groups: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}

        for s in series:
            # Utiliser symlink_destination pour extraire le type et la lettre
            symlink_dest = s.get("symlink_destination")
            series_type = "Séries TV"
            letter = "?"
            if symlink_dest:
                try:
                    rel_path = symlink_dest.relative_to(video_dir)
                    # Structure: Series/{Type}/{Lettre}/{Titre}/{Saison}/fichier
                    parts = rel_path.parts
                    if len(parts) >= 5:
                        series_type = parts[1]  # Series TV, Animation, ou Mangas
                        letter = parts[2]  # Lettre ou plage
                except ValueError:
                    pass

            title = s.get("title", "Inconnu")
            year = s.get("year", "")
            series_key = f"{title} ({year})" if year else title

            dest = s.get("symlink_destination") or s["destination"]
            season_dir = dest.parent.name  # ex: "Saison 01"

            if series_type not in type_groups:
                type_groups[series_type] = {}
            if letter not in type_groups[series_type]:
                type_groups[series_type][letter] = {}
            if series_key not in type_groups[series_type][letter]:
                type_groups[series_type][letter][series_key] = {}
            if season_dir not in type_groups[series_type][letter][series_key]:
                type_groups[series_type][letter][series_key][season_dir] = []
            type_groups[series_type][letter][series_key][season_dir].append(s)

        # Afficher par type, lettre, serie
        for series_type in sorted(type_groups.keys()):
            type_branch = tree.add(f"[bold magenta]Séries/{series_type}/[/bold magenta]")

            for letter in sorted(type_groups[series_type].keys()):
                letter_branch = type_branch.add(f"[magenta]{letter}/[/magenta]")
                for series_name in sorted(type_groups[series_type][letter].keys()):
                    series_sub = letter_branch.add(f"[magenta]{series_name}/[/magenta]")
                    for season in sorted(type_groups[series_type][letter][series_name].keys()):
                        season_sub = series_sub.add(f"[dim]{season}/[/dim]")
                        episodes = type_groups[series_type][letter][series_name][season]
                        # Trier par numero d'episode
                        episodes.sort(key=lambda e: e["new_filename"])
                        for ep in episodes:
                            season_sub.add(f"[green]{ep['new_filename']}[/green]")

    console.print(tree)
