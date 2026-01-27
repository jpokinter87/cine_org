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

# Lazy imports pour eviter les erreurs avant creation de retry.py
__all__ = [
    "APICache",
    "RateLimitError",
    "with_retry",
    "request_with_retry",
]


def __getattr__(name: str):
    """Import paresseux pour RateLimitError et with_retry."""
    if name in ("RateLimitError", "with_retry", "request_with_retry"):
        from src.adapters.api.retry import (
            RateLimitError,
            request_with_retry,
            with_retry,
        )
        return {"RateLimitError": RateLimitError, "with_retry": with_retry, "request_with_retry": request_with_retry}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
