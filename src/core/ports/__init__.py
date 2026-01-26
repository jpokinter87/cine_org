"""
Ports (interfaces abstraites) définissant les contrats pour les adaptateurs.

Les ports sont les frontières de l'architecture hexagonale. Ils définissent
ce dont le domaine a besoin du monde extérieur sans spécifier
comment ces besoins sont satisfaits.

Ports repository : Contrats de persistance des données
- IVideoFileRepository : Stockage des fichiers vidéo
- IMovieRepository : Stockage des métadonnées de films
- ISeriesRepository : Stockage des métadonnées de séries
- IEpisodeRepository : Stockage des métadonnées d'épisodes

Ports client API : Contrats pour les services externes
- IMediaAPIClient : Interface de base pour les APIs de métadonnées média
- SearchResult : Résultat de recherche depuis une API
- MediaDetails : Informations détaillées depuis une API

Ports système de fichiers : Contrats pour les opérations fichiers
- IFileSystem : Opérations de base sur les fichiers
- ISymlinkManager : Opérations de gestion des liens symboliques
"""

from src.core.ports.repositories import (
    IVideoFileRepository,
    IMovieRepository,
    ISeriesRepository,
    IEpisodeRepository,
)
from src.core.ports.api_clients import (
    IMediaAPIClient,
    SearchResult,
    MediaDetails,
)
from src.core.ports.file_system import (
    IFileSystem,
    ISymlinkManager,
)

__all__ = [
    # Repositories
    "IVideoFileRepository",
    "IMovieRepository",
    "ISeriesRepository",
    "IEpisodeRepository",
    # Clients API
    "IMediaAPIClient",
    "SearchResult",
    "MediaDetails",
    # Système de fichiers
    "IFileSystem",
    "ISymlinkManager",
]
