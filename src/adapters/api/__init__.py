"""
Clients API externes pour l'enrichissement des metadonnees.

Ce module fournit les adaptateurs pour communiquer avec les API externes:
- TMDB: The Movie Database pour les films
- TVDB: The TVDB pour les series TV

Infrastructure partagee:
- APICache: Cache persistant avec TTL differencies (recherche 24h, details 7j)
- RateLimitError: Exception pour les erreurs 429
- with_retry: Decorateur avec backoff exponentiel pour gerer le rate limiting

Les clients implementent IMediaAPIClient defini dans core/ports/api_clients.py.
"""

from src.adapters.api.cache import APICache
from src.adapters.api.retry import RateLimitError, request_with_retry, with_retry
from src.adapters.api.tmdb_client import TMDBClient
from src.adapters.api.tvdb_client import TVDBClient

__all__ = [
    "APICache",
    "RateLimitError",
    "with_retry",
    "request_with_retry",
    "TMDBClient",
    "TVDBClient",
]
