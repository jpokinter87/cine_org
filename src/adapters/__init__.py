"""
Couche adaptateurs (infrastructure).

Les adaptateurs implémentent les ports définis dans core/ports/ et fournissent
des implémentations concrètes pour les systèmes externes.

Sous-packages prévus :
- cli/ : Interface ligne de commande (Typer)
- web/ : Interface web (FastAPI + HTMX)
- db/ : Accès base de données (SQLModel + SQLite)
- api/ : Clients API externes (TMDB, TVDB)
- filesystem/ : Opérations sur le système de fichiers
- parsing/ : Parsing de noms de fichiers et extraction mediainfo

Chaque adaptateur dépend de core/ mais core/ ne dépend jamais des adaptateurs.
Cela permet de changer les implémentations sans affecter la logique métier.
"""

from src.adapters.file_system import FileSystemAdapter
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor

__all__ = [
    "FileSystemAdapter",
    "GuessitFilenameParser",
    "MediaInfoExtractor",
]
