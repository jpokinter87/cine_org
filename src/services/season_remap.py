"""
Detection du decalage de saison des arcs livres en cours separes.

Les teams de release decoupent un arc d'anime en cours numerotes S01/S02/S03
(« BLEACH.Thousand-Year.Blood.War.S02E05 ») alors que TMDB et TVDB rangent
l'arc entier dans une seule saison de la serie mere, a numerotation continue
(Bleach TYBW = saison 17 de BLEACH, episodes 1 a 50). Sans realignement, les
fichiers heritent des numeros — et donc des titres — d'une saison sans rapport.

Deux signaux, tous deux verifiables, permettent de retrouver la bonne cible :

1. le nom de la saison chez le fournisseur (« Bleach: Thousand-Year Blood War »)
   apparait dans le nom de fichier, en plus du titre de la serie ;
2. les cours d'une meme saison sont separes par plusieurs mois de diffusion :
   grouper les episodes sur un ecart de dates redonne le decoupage des releases.

Ce module se contente de *proposer* : la decision reste a l'utilisateur, une
detection interdisant l'auto-validation plutot que de renommer d'autorite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from loguru import logger

from src.services.repair.filename_analyzer import normalize_filename
from src.utils.helpers import normalize_accents

# Ecart de diffusion a partir duquel deux episodes appartiennent a deux cours.
# Les cours d'un meme arc sont espaces de 6 mois ou plus ; a l'interieur d'un
# cour, les episodes sont hebdomadaires (pauses ponctuelles incluses).
COUR_GAP_DAYS = 90


@dataclass(frozen=True)
class SeasonRemap:
    """
    Realignement propose d'un episode livre en cour sur la saison canonique.

    Attributs :
        source_season : numero de saison lu dans le nom de fichier (le cour)
        source_episode : numero d'episode lu dans le nom de fichier
        target_season : saison canonique chez le fournisseur
        target_episode : numero d'episode dans la numerotation continue
        season_name : nom de la saison canonique ayant permis la detection
        cour : rang du cour dans la saison (1 pour le premier)
    """

    source_season: int
    source_episode: int
    target_season: int
    target_episode: int
    season_name: str
    cour: int

    @property
    def label(self) -> str:
        """Libelle affiche a l'utilisateur pour arbitrer la proposition."""
        return (
            f"cour {self.cour} de « {self.season_name} » → "
            f"S{self.target_season:02d}E{self.target_episode:02d} "
            f"(au lieu de S{self.source_season:02d}E{self.source_episode:02d})"
        )


def _tokens(text: str) -> list[str]:
    """Tokens normalises : minuscules, sans accents, separateurs ni ponctuation."""
    cleaned = re.sub(r"[^\w\s]", " ", normalize_filename(text), flags=re.UNICODE)
    return normalize_accents(cleaned).lower().split()


def _extra_tokens(filename: str, series_title: str) -> list[str]:
    """
    Tokens du nom de fichier absents du titre de la serie.

    Sert de garde-fou peu couteux : sans token en trop, le fichier ne porte
    aucun nom d'arc et la detection s'arrete avant tout appel reseau.
    """
    known = set(_tokens(series_title))
    extra = []
    for token in _tokens(filename):
        # Le marqueur SxxExx clot la partie « titre » du nom de fichier.
        if len(token) >= 6 and token[0] == "s" and token[1:3].isdigit():
            if "e" in token[3:]:
                break
        if token not in known:
            extra.append(token)
    return extra


def _match_season(
    season_names: dict[int, tuple[str, ...]],
    extra: list[str],
    series_title: str,
) -> Optional[tuple[int, str]]:
    """
    Trouve la saison dont le nom est contenu dans les tokens en trop.

    Le titre de la serie est retire du nom de saison avant comparaison : les
    fournisseurs le prefixent souvent (« Bleach: Thousand-Year Blood War »)
    alors qu'il a deja ete consomme cote nom de fichier.

    Retourne le nom le plus long ayant matche : quand plusieurs saisons
    partagent un prefixe, le nom le plus specifique gagne.
    """
    known = set(_tokens(series_title))
    haystack = " ".join(extra)
    best: Optional[tuple[int, str, int]] = None
    for number, names in season_names.items():
        for name in names:
            needle_tokens = [t for t in _tokens(name) if t not in known]
            needle = " ".join(needle_tokens)
            if not needle or needle not in haystack:
                continue
            if best is None or len(needle) > best[2]:
                best = (number, name, len(needle))
    return (best[0], best[1]) if best else None


def _split_into_cours(episodes: list) -> list[list]:
    """
    Regroupe les episodes d'une saison en cours, par ecart de diffusion.

    Les episodes sans date sont ecartes : un decoupage partiel produirait des
    numeros faux, on prefere ne rien proposer.
    """
    dated = []
    for episode in episodes:
        if not episode.air_date:
            continue
        try:
            dated.append((date.fromisoformat(str(episode.air_date)[:10]), episode))
        except ValueError:
            continue

    if not dated:
        return []

    dated.sort(key=lambda pair: pair[0])
    cours: list[list] = [[]]
    previous: Optional[date] = None
    for aired, episode in dated:
        if previous is not None and (aired - previous).days > COUR_GAP_DAYS:
            cours.append([])
        cours[-1].append(episode)
        previous = aired
    return cours


async def detect_season_remap(
    tvdb_client,
    series_id: str,
    series_title: str,
    filename: str,
    season: int,
    episode: int,
) -> Optional[SeasonRemap]:
    """
    Propose le realignement d'un episode livre en cour sur sa saison canonique.

    Args:
        tvdb_client: client exposant ``get_season_names`` et ``get_all_episodes``
        series_id: ID TVDB de la serie retenue
        series_title: titre de la serie retenue
        filename: nom du fichier a transferer
        season: numero de saison lu dans le nom de fichier
        episode: numero d'episode lu dans le nom de fichier

    Returns:
        Le realignement propose, ou None si aucun n'est etabli avec certitude.
        Toute incertitude (aucun nom de saison reconnu, cour absent, dates
        manquantes, panne API) rend None : le fichier part en validation
        manuelle plutot que d'etre renumerote a tort.
    """
    if tvdb_client is None or not series_id:
        return None

    extra = _extra_tokens(filename, series_title)
    if not extra:
        return None

    try:
        season_names = await tvdb_client.get_season_names(str(series_id))
        matched = _match_season(season_names or {}, extra, series_title)
        if matched is None:
            return None

        target_season, season_name = matched
        if target_season == season:
            return None

        all_episodes = await tvdb_client.get_all_episodes(str(series_id))
    except Exception as e:
        logger.debug(
            "Detection de decalage de saison abandonnee pour {} : {}", filename, e
        )
        return None

    cours = _split_into_cours(
        [ep for ep in all_episodes or [] if ep.season_number == target_season]
    )
    if season < 1 or season > len(cours):
        return None

    cour = cours[season - 1]
    if episode < 1 or episode > len(cour):
        return None

    return SeasonRemap(
        source_season=season,
        source_episode=episode,
        target_season=target_season,
        target_episode=cour[episode - 1].episode_number,
        season_name=season_name,
        cour=season,
    )
