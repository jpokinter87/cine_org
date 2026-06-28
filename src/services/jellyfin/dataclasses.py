"""Objets de données pour la synchronisation Jellyfin."""

from dataclasses import dataclass, field


@dataclass
class JellyfinSyncReport:
    """Bilan d'une exécution de `jellyfin-sync`.

    - movies / series / episodes : éléments effectivement liés (NFO + symlink).
    - skipped : sources introuvables (chaîne de repli épuisée).
    - id_less : œuvres sans identifiant TMDB/TVDB (liées quand même, titre/année).
    - pruned : entrées supprimées de l'arbre Jellyfin (option --prune).
    - errors : messages d'erreur non bloquants rencontrés.
    """

    movies: int = 0
    series: int = 0
    episodes: int = 0
    skipped: list[str] = field(default_factory=list)
    id_less: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
