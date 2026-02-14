"""
Calcul de similarite entre noms de fichiers video.

Fournit les algorithmes de comparaison floue pour trouver des cibles
de reparation pour les symlinks casses.
"""

import re
from difflib import SequenceMatcher
from pathlib import Path

from .filename_analyzer import extract_series_info


def calculate_similarity_fast(norm1: str, norm2: str) -> float:
    """
    Calcule rapidement la similarite entre deux noms deja normalises.

    Version optimisee qui assume que les noms sont deja normalises.
    Pour les series, compare le titre et l'episode separement.
    """
    # Extraire les informations structurees
    title1, season1, episode1, year1 = extract_series_info(norm1)
    title2, season2, episode2, year2 = extract_series_info(norm2)

    # Similarite des titres
    if title1 and title2:
        title_ratio = SequenceMatcher(None, title1, title2).ratio()
    else:
        # Fallback sur la comparaison directe
        title_ratio = SequenceMatcher(None, norm1, norm2).ratio()

    # Pour les series: bonus/malus selon correspondance episode
    if season1 is not None and episode1 is not None:
        # C'est une serie
        if season2 == season1 and episode2 == episode1:
            # Meme episode: gros bonus
            return min(100.0, title_ratio * 100 + 30)
        elif season2 == season1 and episode2 is not None:
            # Meme saison mais episode different: malus
            return max(0.0, title_ratio * 100 - 20)
        elif episode2 is not None:
            # Saison differente: malus important
            return max(0.0, title_ratio * 100 - 30)

    # Pour les films ou si pas d'info episode: comparaison simple
    score = title_ratio * 100

    # Bonus/malus pour l'annee
    if year1 and year2:
        if year1 == year2:
            score = min(100.0, score + 10)
        elif abs(year1 - year2) > 2:
            score = max(0.0, score - 10)

    return score


def calculate_title_similarity(name1: str, name2: str) -> float:
    """
    Calcule la similarite entre deux noms de fichiers video.

    Extrait les titres et annees, puis compare avec SequenceMatcher.

    Args:
        name1: Premier nom de fichier
        name2: Deuxieme nom de fichier

    Returns:
        Score de similarite (0-100)
    """

    def normalize_and_extract(name: str) -> tuple[str, int | None]:
        """Normalise un nom et extrait titre + annee."""
        # Supprimer l'extension
        stem = Path(name).stem.lower()

        # Remplacer les separateurs
        for sep in [".", "_", "-"]:
            stem = stem.replace(sep, " ")

        # Chercher une annee
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", stem)
        year = int(year_match.group(1)) if year_match else None

        # Extraire le titre (avant l'annee ou infos techniques)
        title = stem
        if year_match:
            title = stem[: year_match.start()]

        # Supprimer les infos techniques
        tech_patterns = [
            r"\b(french|vostfr|multi|truefrench|vff|vf|vo|eng)\b",
            r"\b(720p|1080p|2160p|4k|uhd)\b",
            r"\b(x264|x265|hevc|h264|h265|avc)\b",
            r"\b(bluray|bdrip|webrip|hdtv|dvdrip|web)\b",
            r"\b(dts|ac3|aac|dolby|atmos|truehd|dd|ddp)\b",
            r"\b(remux|proper|repack)\b",
        ]
        for pattern in tech_patterns:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE)

        # Nettoyer les espaces
        while "  " in title:
            title = title.replace("  ", " ")

        return title.strip(), year

    title1, year1 = normalize_and_extract(name1)
    title2, year2 = normalize_and_extract(name2)

    # Similarite des titres
    title_ratio = SequenceMatcher(None, title1, title2).ratio()

    # Bonus/malus pour l'annee
    year_bonus = 0.0
    if year1 and year2:
        if year1 == year2:
            year_bonus = 0.15  # +15% si meme annee
        elif abs(year1 - year2) <= 1:
            year_bonus = 0.05  # +5% si annee proche
        else:
            year_bonus = -0.15  # -15% si annee differente

    score = (title_ratio + year_bonus) * 100
    return max(0.0, min(100.0, score))
