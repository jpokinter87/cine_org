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
