"""
Mecanisme de retry avec backoff exponentiel pour les API externes.

Gere automatiquement les erreurs 429 (rate limiting) en relancant
les requetes avec un delai croissant et du jitter aleatoire.

Usage:
    # Avec le decorateur
    @with_retry(max_attempts=5, max_wait=60)
    async def my_api_call():
        ...

    # Avec la fonction helper
    response = await request_with_retry(client, "GET", url)
"""

from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)


class RateLimitError(Exception):
    """
    Exception levee quand l'API retourne 429 Too Many Requests.

    Attributes:
        retry_after: Nombre de secondes a attendre (depuis le header Retry-After),
                     ou None si non specifie.
    """

    def __init__(self, retry_after: Optional[int] = None) -> None:
        """
        Initialise l'erreur avec la valeur Retry-After optionnelle.

        Args:
            retry_after: Secondes a attendre avant de relancer (optionnel)
        """
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after: {retry_after}s")


def with_retry(max_attempts: int = 5, max_wait: int = 60):
    """
    Decorateur pour relancer sur RateLimitError avec backoff exponentiel.

    Utilise wait_random_exponential pour ajouter du jitter et eviter
    le "thundering herd" quand plusieurs clients relancent en meme temps.

    Args:
        max_attempts: Nombre maximum de tentatives (defaut: 5)
        max_wait: Delai maximum entre les tentatives en secondes (defaut: 60)

    Returns:
        Decorateur a appliquer sur une fonction async

    Example:
        @with_retry(max_attempts=3, max_wait=30)
        async def fetch_data():
            # Sera relance jusqu'a 3 fois si RateLimitError est levee
            ...
    """
    return retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_random_exponential(multiplier=1, min=1, max=max_wait),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_attempts: int = 5,
    **kwargs,
) -> httpx.Response:
    """
    Execute une requete HTTP avec retry automatique sur 429.

    Convertit les reponses 429 en RateLimitError et relance avec
    backoff exponentiel. Les autres erreurs HTTP (4xx, 5xx) sont
    propagees immediatement sans retry.

    Args:
        client: Client httpx async a utiliser
        method: Methode HTTP (GET, POST, etc.)
        url: URL a appeler
        max_attempts: Nombre maximum de tentatives (defaut: 5)
        **kwargs: Arguments supplementaires passes a client.request()

    Returns:
        httpx.Response en cas de succes

    Raises:
        RateLimitError: Si 429 apres epuisement des tentatives
        httpx.HTTPStatusError: Pour les autres erreurs HTTP

    Example:
        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.tmdb.org/3/movie/123",
                headers={"Authorization": f"Bearer {token}"}
            )
    """

    @with_retry(max_attempts=max_attempts)
    async def _do_request() -> httpx.Response:
        response = await client.request(method, url, **kwargs)
        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = int(retry_after_header) if retry_after_header else None
            raise RateLimitError(retry_after)
        response.raise_for_status()
        return response

    return await _do_request()
