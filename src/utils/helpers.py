"""
Fonctions utilitaires partagees dans le projet CineOrg.

Ce module centralise les fonctions reutilisees a travers le codebase :
- normalize_accents : suppression des diacritiques pour comparaison
- strip_article : retrait de l'article initial d'un titre
- parse_candidate / parse_candidates : conversion dict -> SearchResult
- resolve_episode_end : validation d'une plage d'episodes (fichiers multi-episodes)
"""

import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from src.core.ports.api_clients import SearchResult
from src.utils.constants import IGNORED_ARTICLES

# Ecart maximal tolere entre le premier et le dernier episode d'un meme
# fichier. Au-dela, la « plage » vient presque toujours d'un faux positif de
# parsing (ex. « S05E28-40 detectives plus tard » ou 40 est un mot du titre).
MAX_EPISODE_SPAN = 3


def resolve_episode_end(start: Optional[int], end: Optional[int]) -> Optional[int]:
    """
    Valide la plage d'episodes couverte par un fichier multi-episodes.

    Args:
        start : Premier episode couvert (numero du fichier)
        end : Dernier episode couvert, tel que parse

    Returns:
        Le dernier episode couvert, ou None si la plage est absente,
        degeneree (end <= start) ou invraisemblable (ecart trop grand).
    """
    if start is None or end is None:
        return None
    if end <= start or end - start > MAX_EPISODE_SPAN:
        return None
    return end


def strip_invisible_chars(text: str) -> str:
    """
    Retire les caractères Unicode invisibles d'une chaîne.

    Supprime les caractères de contrôle et les marques directionnelles
    qui peuvent provenir des APIs (LRM, RLM, BOM, etc.).
    """
    result = []
    for char in text:
        category = unicodedata.category(char)
        if category in ("Cf", "Cc"):
            continue
        result.append(char)
    return "".join(result)


def clean_title(title: str) -> str:
    """Nettoie un titre : retire les caractères invisibles et les espaces superflus."""
    if not title:
        return title
    return strip_invisible_chars(title).strip()


_LIGATURE_MAP = {"œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae"}
_REVERSE_LIGATURE_MAP = {v: k for k, v in _LIGATURE_MAP.items()}


def _expand_ligatures(text: str) -> str:
    """Remplace les ligatures Unicode par leurs équivalents ASCII pour le tri."""
    for lig, expanded in _LIGATURE_MAP.items():
        text = text.replace(lig, expanded)
    return text


def search_variants(query: str) -> list[str]:
    """
    Génère les variantes de recherche pour gérer ligatures + accents.

    SQLite LIKE est case-insensitive pour ASCII uniquement.
    - Ligatures Unicode (œ, æ) : combinaisons casse + forme (ligature vs digraphe).
    - Accents (é, à, ç…) : inclusion de la forme accent-stripped pour
      que la condition ``column.contains(variant)`` puisse matcher les
      titres sans accent même quand la query en contient (et via l'UDF
      ``unaccent`` côté SQL, le sens inverse est couvert aussi — phase 43-01).
    """
    variants = {query, query.lower(), query.capitalize()}
    # Déplier les ligatures (ex: "œil" → "oeil")
    expanded = query
    for lig, exp in _LIGATURE_MAP.items():
        expanded = expanded.replace(lig, exp)
    variants.update({expanded, expanded.lower(), expanded.capitalize()})
    # Replier les digraphes en ligatures (ex: "oeil" → "œil")
    collapsed = query.lower()
    for exp, lig in _REVERSE_LIGATURE_MAP.items():
        collapsed = collapsed.replace(exp, lig)
    variants.update({collapsed, collapsed.capitalize()})
    # Version accent-stripped de chaque variante (phase 43-01)
    variants.update({normalize_accents(v) for v in list(variants)})
    # Retirer les doublons tout en gardant un ordre stable
    return list(variants)


def title_sort_key(title: str) -> str:
    """
    Clé de tri normalisée pour un titre.

    Applique dans l'ordre : nettoyage invisibles, expansion ligatures,
    suppression caractères non-alphanumériques de tête,
    suppression article, normalisation accents, mise en minuscules.
    """
    cleaned = strip_invisible_chars(title)
    cleaned = _expand_ligatures(cleaned)
    # Retirer tous les caractères non-alphanumériques en début de titre
    # (gère …, ', ", etc. y compris les variantes typographiques Unicode)
    idx = 0
    for i, ch in enumerate(cleaned):
        if ch.isalnum():
            idx = i
            break
    stripped = cleaned[idx:] if cleaned else cleaned
    return normalize_accents(strip_article(stripped)).lower()


def normalize_accents(text: str) -> str:
    """
    Supprime les accents d'une chaine pour une comparaison insensible aux accents.

    Utilise la decomposition NFD puis filtre les caracteres diacritiques (Mn).
    Ex: "Les Evades" -> "Les Evades"
    """
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


_TRAILING_YEAR_RE = re.compile(r"\s*\(\d{4}\)\s*$")


def strip_trailing_year(title: str) -> str:
    """
    Retire une année entre parenthèses en fin de titre.

    « Surface (2025) » -> « Surface ». Évite la double année dans les chemins et
    noms de fichiers (ex. « Surface (2025) (2025) ») quand le titre stocké
    embarque déjà l'année alors que celle-ci est rajoutée depuis le champ `year`.

    Seule une année strictement finale entre parenthèses est retirée ; une
    parenthèse non-année ou une année au milieu du titre est préservée.

    Args:
        title: Titre éventuellement suffixé de « (AAAA) ».

    Returns:
        Titre sans l'année finale, espaces de bord nettoyés.
    """
    return _TRAILING_YEAR_RE.sub("", title).strip()


def strip_article(title: str) -> str:
    """
    Retire l'article initial d'un titre.

    Gere les articles francais, anglais, allemands et espagnols.
    Gere egalement l'apostrophe (L'Odyssee -> Odyssee).

    Args:
        title: Titre complet.

    Returns:
        Titre sans l'article initial.
    """
    if not title:
        return title

    title_lower = title.lower()

    # Cas special de l'apostrophe (L'Odyssee, L'Amour, etc.)
    for article in IGNORED_ARTICLES:
        if article.endswith("'"):
            if title_lower.startswith(article):
                rest = title[len(article) :]
                if rest:
                    return rest

    # Articles standards (separes par espace)
    words = title.split(None, 1)
    if len(words) >= 2:
        first_word = words[0].lower()
        if first_word in IGNORED_ARTICLES:
            return words[1]

    return title


def parse_candidate(candidate) -> SearchResult:
    """
    Convertit un candidat (dict ou SearchResult) en SearchResult.

    Args:
        candidate: Dict avec les cles id, title, year, score, source
                   ou SearchResult deja construit.

    Returns:
        SearchResult
    """
    if isinstance(candidate, SearchResult):
        return candidate
    return SearchResult(
        id=candidate.get("id", ""),
        title=candidate.get("title", ""),
        year=candidate.get("year"),
        score=candidate.get("score", 0.0),
        source=candidate.get("source", ""),
        original_title=candidate.get("original_title"),
    )


def parse_candidates(candidates: list) -> list[SearchResult]:
    """
    Convertit une liste de candidats (dicts ou SearchResult) en liste de SearchResult.

    Args:
        candidates: Liste de candidats (dict ou SearchResult)

    Returns:
        Liste de SearchResult
    """
    if not candidates:
        return []
    return [parse_candidate(c) for c in candidates]


def managed_roots(base: Path, subdirs: Optional[Sequence[str]] = None) -> list[Path]:
    """
    Retourne les racines a balayer sous ``base``, limitees aux dossiers geres.

    storage/ et video/ hebergent aussi des contenus etrangers a la videotheque.
    Restreindre les parcours aux sous-repertoires geres evite d'indexer des
    dizaines de milliers de fichiers inutiles et de rapporter des anomalies sur
    des contenus hors perimetre.

    Si aucun des sous-repertoires geres n'existe, ``base`` est renvoye tel quel :
    une installation organisee autrement continue de fonctionner.

    Args:
        base: Racine (storage_dir ou video_dir)
        subdirs: Noms des sous-repertoires geres (defaut: MANAGED_SUBDIRS)

    Returns:
        Liste des repertoires a parcourir, dans l'ordre de ``subdirs``
    """
    from src.utils.constants import MANAGED_SUBDIRS

    base = Path(base)
    roots = [
        base / name
        for name in (subdirs if subdirs is not None else MANAGED_SUBDIRS)
        if (base / name).is_dir()
    ]
    return roots or [base]
