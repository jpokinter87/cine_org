"""Construction de l'arbre de symlinks dédié à Jellyfin.

Résolution de la source (chaîne de repli), calcul des noms à plat, création
idempotente des symlinks.
"""

import shutil
from pathlib import Path

from src.services.renamer import sanitize_for_filesystem


def resolve_source(symlink_path: str | None, file_path: str | None) -> Path | None:
    """Résout le fichier physique réel à lier.

    Chaîne de repli : `realpath(symlink_path)` s'il résout vers un fichier
    présent, sinon `file_path` s'il existe, sinon None.
    """
    for candidate in (symlink_path, file_path):
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():  # suit les symlinks ; True seulement si la cible existe
            return p.resolve()
    return None


def folder_name(
    title: str, year: int | None, tmdb_id: int | None = None, with_id: bool = False
) -> str:
    """Nom de dossier à plat : `Titre (Année)`, avec suffixe `[tmdbid-N]` en cas de collision."""
    base = sanitize_for_filesystem(title)
    if year is not None:
        base = f"{base} ({year})"
    if with_id and tmdb_id is not None:
        base = f"{base} [tmdbid-{tmdb_id}]"
    return base


def episode_filename(
    title: str, year: int | None, season: int, episode: int, ext: str
) -> str:
    """Nom de fichier d'épisode : `Titre (Année) SxxExx.ext`."""
    ext = ext if ext.startswith(".") else f".{ext}"
    base = sanitize_for_filesystem(title)
    if year is not None:
        base = f"{base} ({year})"
    return f"{base} S{season:02d}E{episode:02d}{ext}"


def ensure_symlink(target: Path, link_path: Path) -> None:
    """Crée (ou corrige) un symlink `link_path -> target`, de façon idempotente.

    `target` doit être un chemin absolu (résolu). Gère le remplacement d'un
    lien incorrect, d'un fichier régulier ou d'un répertoire déjà présent à
    l'emplacement du lien (l'arbre Jellyfin est entièrement régénérable).
    """
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if link_path.resolve() == target.resolve():
            return
        link_path.unlink()
    elif link_path.is_dir():
        shutil.rmtree(link_path)
    elif link_path.exists():
        link_path.unlink()
    link_path.symlink_to(target)


def unique_folder_name(
    title: str, year: int | None, tmdb_id: int | None, used: set[str]
) -> str:
    """Nom de dossier unique dans `used` : `Titre (Année)`, sinon suffixe
    `[tmdbid-N]`, sinon suffixe numérique ` [n]` (cas homonymes sans tmdb_id)."""
    candidate = folder_name(title, year)
    if candidate not in used:
        return candidate
    candidate = folder_name(title, year, tmdb_id, with_id=True)
    if candidate not in used:
        return candidate
    base = folder_name(title, year)
    n = 2
    while f"{base} [{n}]" in used:
        n += 1
    return f"{base} [{n}]"
