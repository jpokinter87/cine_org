"""
Fonctions d'analyse et normalisation de noms de fichiers video.

Fournit les utilitaires de normalisation, extraction de titre propre
via guessit, et extraction d'informations structurees pour les series.
"""

import re
from pathlib import Path


def normalize_filename(name: str) -> str:
    """Normalise un nom de fichier pour comparaison."""
    stem = Path(name).stem.lower()
    for sep in [".", "_", "-"]:
        stem = stem.replace(sep, " ")
    return stem


def extract_clean_title(name: str) -> str:
    """
    Extrait le titre pur d'un nom de fichier via guessit.

    Args:
        name: Nom du fichier

    Returns:
        Titre nettoye (minuscules)
    """
    from guessit import guessit

    try:
        result = guessit(name)
        title = result.get("title", "")
        if title:
            # Nettoyer le titre des termes techniques que guessit laisse passer
            title = title.lower()
            # Retirer 3D, Top-Bottom, Top-Bot, etc.
            cleanup_terms = [
                r"\b3d\b", r"\btop[-\s]?bottom\b", r"\btop[-\s]?bot\b",
                r"\bsbs\b", r"\bhsbs\b", r"\bhalf[-\s]?sbs\b",
                r"\bou\b", r"\bhou\b",  # Over-Under
            ]
            for term in cleanup_terms:
                title = re.sub(term, "", title, flags=re.IGNORECASE)
            # Nettoyer les espaces multiples
            title = " ".join(title.split())
            return title.strip()
    except Exception:
        pass

    # Fallback: retourner le stem normalise
    return normalize_filename(name)


def extract_series_info(name: str) -> tuple[str, str | None, int | None, int | None]:
    """
    Extrait les informations structurees d'un nom de fichier de serie.

    Args:
        name: Nom du fichier

    Returns:
        Tuple (titre_normalise, saison, episode, annee)
    """
    stem = Path(name).stem.lower()

    # Remplacer les separateurs
    for sep in [".", "_", "-"]:
        stem = stem.replace(sep, " ")

    # Extraire saison/episode (S01E03, S01 E03, 1x03, etc.)
    season = None
    episode = None
    episode_match = re.search(r"\bs(\d{1,2})\s*e(\d{1,2})\b", stem)
    if episode_match:
        season = int(episode_match.group(1))
        episode = int(episode_match.group(2))
    else:
        # Format alternatif 1x03
        alt_match = re.search(r"\b(\d{1,2})x(\d{1,2})\b", stem)
        if alt_match:
            season = int(alt_match.group(1))
            episode = int(alt_match.group(2))

    # Extraire l'annee
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", stem)
    year = int(year_match.group(1)) if year_match else None

    # Extraire le titre (tout avant SxxExx ou l'annee)
    title = stem
    if episode_match:
        title = stem[: episode_match.start()].strip()
    elif year_match:
        title = stem[: year_match.start()].strip()

    # Nettoyer le titre des termes techniques
    tech_terms = [
        "french", "vostfr", "multi", "truefrench", "vff", "vf", "vo",
        "720p", "1080p", "2160p", "4k", "uhd",
        "x264", "x265", "hevc", "h264", "h265", "avc",
        "bluray", "bdrip", "webrip", "hdtv", "dvdrip", "web dl", "web",
        "dts", "ac3", "aac", "dolby", "atmos", "truehd",
        "internal", "final", "repack", "proper",
    ]
    for term in tech_terms:
        title = re.sub(rf"\b{term}\b", "", title, flags=re.IGNORECASE)

    # Nettoyer les espaces multiples
    title = " ".join(title.split())

    return title, season, episode, year
