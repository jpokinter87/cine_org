"""Suggestion de collections locales à partir des préfixes de titres communs.

Algorithme V1 volontairement simple :

1. On récupère les courts orphelins : ``is_short=True``, sans
   ``collection_name`` TMDB, sans ``local_collection_id``.
2. On extrait le préfixe sur 2 mots de chaque titre.
3. On regroupe par préfixe identique (insensible à la casse mais on conserve
   l'écriture du premier film pour l'affichage). Les groupes contenant moins
   de 2 films sont écartés.
4. Le nom suggéré pour la nouvelle collection locale est le préfixe normalisé
   (forme du premier film rencontré).

La sortie alimente la commande CLI ``cineorg collections suggest``.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session, select

from src.infrastructure.persistence.models import MovieModel


_PREFIX_WORD_COUNT = 2
_MIN_GROUP_SIZE = 2


@dataclass(frozen=True)
class OrphanGroup:
    """Groupe de courts partageant le même préfixe de titre."""

    suggested_name: str
    movies: list[MovieModel]


def _title_prefix(title: str) -> Optional[tuple[str, str]]:
    """Renvoie ``(clé_normalisée, préfixe_affichage)`` ou ``None`` si trop court.

    La clé est la version lower-case des deux premiers mots (utilisée pour
    le regroupement) ; le préfixe d'affichage est l'écriture originale.
    """
    if not title:
        return None
    words = title.split()
    if len(words) < _PREFIX_WORD_COUNT:
        return None
    prefix_words = words[:_PREFIX_WORD_COUNT]
    key = " ".join(w.lower() for w in prefix_words)
    display = " ".join(prefix_words)
    return key, display


class LocalCollectionSuggester:
    """Service de suggestion de regroupements pour courts orphelins."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_orphan_groups(self) -> list[OrphanGroup]:
        """Regroupe les courts orphelins par préfixe de titre commun."""
        stmt = (
            select(MovieModel)
            .where(MovieModel.is_short == True)  # noqa: E712
            .where(MovieModel.collection_name.is_(None))
            .where(MovieModel.local_collection_id.is_(None))
        )
        buckets: dict[str, tuple[str, list[MovieModel]]] = defaultdict(lambda: ("", []))
        for movie in self._session.exec(stmt).all():
            prefix = _title_prefix(movie.title or "")
            if prefix is None:
                continue
            key, display = prefix
            current_display, members = buckets[key]
            if not current_display:
                current_display = display
            members.append(movie)
            buckets[key] = (current_display, members)

        groups: list[OrphanGroup] = []
        for _, (display, members) in sorted(buckets.items()):
            if len(members) < _MIN_GROUP_SIZE:
                continue
            groups.append(OrphanGroup(suggested_name=display, movies=members))
        return groups
