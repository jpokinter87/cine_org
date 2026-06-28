"""Construction de l'arbre de symlinks dédié à Jellyfin.

Résolution de la source (chaîne de repli), calcul des noms à plat, création
idempotente des symlinks.
"""

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
    if year:
        base = f"{base} ({year})"
    if with_id and tmdb_id is not None:
        base = f"{base} [tmdbid-{tmdb_id}]"
    return base


def episode_filename(
    title: str, year: int | None, season: int, episode: int, ext: str
) -> str:
    """Nom de fichier d'épisode : `Titre (Année) SxxExx.ext`."""
    base = sanitize_for_filesystem(title)
    if year:
        base = f"{base} ({year})"
    return f"{base} S{season:02d}E{episode:02d}{ext}"


def ensure_symlink(target: Path, link_path: Path) -> None:
    """Crée (ou corrige) un symlink `link_path -> target`, de façon idempotente."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if link_path.readlink() == target:
            return
        link_path.unlink()
    elif link_path.exists():
        link_path.unlink()
    link_path.symlink_to(target)
