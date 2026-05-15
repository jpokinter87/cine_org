"""
Utilitaires partagés du package migration.

Évite les duplications inter-modules et centralise les conversions sûres
souvent appelées sur des chaînes provenant d'API externes (IDs TMDB/TVDB
parfois numériques, parfois alphanumériques).
"""

from __future__ import annotations

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
