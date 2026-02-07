"""
Fonctions utilitaires partagees dans le projet CineOrg.

Ce module centralise les fonctions reutilisees a travers le codebase :
- normalize_accents : suppression des diacritiques pour comparaison
- strip_article : retrait de l'article initial d'un titre
- parse_candidate / parse_candidates : conversion dict -> SearchResult
"""

import unicodedata

from src.core.ports.api_clients import SearchResult
from src.utils.constants import IGNORED_ARTICLES


def normalize_accents(text: str) -> str:
    """
    Supprime les accents d'une chaine pour une comparaison insensible aux accents.

    Utilise la decomposition NFD puis filtre les caracteres diacritiques (Mn).
    Ex: "Les Evades" -> "Les Evades"
    """
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


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
                rest = title[len(article):]
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
