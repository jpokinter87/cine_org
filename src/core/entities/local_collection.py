"""Entité ``LocalCollection`` : regroupement local de films.

Sert principalement à regrouper des courts-métrages qui ne sont pas dans une
collection TMDB (ex. cartoons Hanna-Barbera) mais qu'on veut quand même voir
ensemble dans ``Films/Courts/{name}/``. Quand un film est rattaché à une
collection locale, son nom prend le pas sur le fallback ``Divers`` du
routage, mais le ``collection_name`` TMDB reste prioritaire s'il est défini.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class LocalCollection:
    """Regroupement local nommé (CRUD via ``LocalCollectionRepository``)."""

    name: str
    id: Optional[int] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
