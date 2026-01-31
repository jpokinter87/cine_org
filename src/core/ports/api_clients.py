"""
Interfaces ports pour les clients API.

Interfaces abstraites (ports) définissant les contrats pour les APIs média externes.
Les implémentations (adaptateurs) fourniront les clients API concrets
(TMDB pour les films, TVDB pour les séries TV).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    """
    Résultat de recherche depuis une API média.

    Représente un résultat unique d'une requête de recherche API.
    Plusieurs résultats sont retournés et scorés par rapport à la requête originale.

    Attributs :
        id : ID spécifique à l'API (ID TMDB ou ID TVDB)
        title : Titre localisé depuis l'API
        original_title : Titre en langue originale (pour matching bilingue)
        year : Année de sortie/diffusion
        score : Score de correspondance (0-100) calculé par le matcher
        source : Identifiant de la source API ("tmdb" ou "tvdb")
    """

    id: str
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    score: float = 0.0
    source: str = ""


@dataclass
class MediaDetails:
    """
    Informations média détaillées depuis l'API.

    Informations étendues récupérées après sélection d'une correspondance.
    Utilisées pour enrichir l'entrée en base de données locale.

    Attributs :
        id : ID spécifique à l'API
        title : Titre localisé
        original_title : Titre en langue originale
        year : Année de sortie/diffusion
        genres : Tuple des noms de genre
        duration_seconds : Durée en secondes (pour les films)
        overview : Résumé de l'intrigue/description
        poster_url : URL complète vers l'image poster
    """

    id: str
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None


class IMediaAPIClient(ABC):
    """
    Interface de base pour les APIs de métadonnées média.

    Définit le contrat pour rechercher et récupérer des informations média
    depuis des APIs externes. Les implémentations gèrent TMDB (films) et TVDB (séries).
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Recherche des médias par titre.

        Args :
            query : Requête de recherche (titre)
            year : Filtre optionnel par année pour affiner les résultats

        Retourne :
            Liste des résultats de recherche, non scorés (scoring fait par le matcher)
        """
        ...

    @abstractmethod
    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Récupère les informations détaillées pour un média spécifique.

        Args :
            media_id : ID spécifique à l'API

        Retourne :
            Informations média détaillées, ou None si non trouvé
        """
        ...

    @property
    @abstractmethod
    def source(self) -> str:
        """Retourne l'identifiant de la source API (ex: 'tmdb', 'tvdb')."""
        ...
