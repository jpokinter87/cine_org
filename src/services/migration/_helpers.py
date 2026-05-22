"""
Utilitaires partagés du package migration.

Évite les duplications inter-modules et centralise les conversions sûres
souvent appelées sur des chaînes provenant d'API externes (IDs TMDB/TVDB
parfois numériques, parfois alphanumériques).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def safe_int(value: object) -> Optional[int]:
    """Convertit en int ou retourne None pour les valeurs non convertibles.

    Accepte str/int/float/None — toute autre entrée renvoie None.
    Utilisé pour les IDs externes (tmdb/tvdb) qui peuvent être absents
    ou non strictement numériques selon la source.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def is_series_like(media_root: str | None, *paths: Optional[Path]) -> bool:
    """True si l'item est probablement un épisode de série / animation.

    Détecte de 2 façons (suffit qu'une matche) :
    - `media_root` commence par "seri", "séri" ou "anim" (cas standard
      où le scanner a identifié la catégorie comme 1er segment).
    - L'un des `paths` contient un segment "Séries/Series/Animation/
      Animations" (cas NAS nested : scanner pointé sur un parent au-dessus
      des catégories, ex. `/media/wd/NAS/` → media_root = "NAS").
    """
    media_root_lower = (media_root or "").lower()
    if media_root_lower.startswith(("seri", "séri", "anim")):
        return True
    for p in paths:
        if p is None:
            continue
        path_str_lower = str(p).lower()
        if any(
            f"/{cat}/" in path_str_lower
            for cat in ("animations", "animation", "séries", "series")
        ):
            return True
    return False
