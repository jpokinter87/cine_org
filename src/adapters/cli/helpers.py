"""
Utilitaires partages pour les commandes CLI de CineOrg.

Ce module fournit :
- suppress_loguru : context manager pour desactiver/reactiver les logs loguru
- with_container : decorateur injectant un container initialise
- async_command : decorateur transformant une fonction async en commande sync
"""

import asyncio
import inspect
from contextlib import contextmanager
from functools import wraps

from loguru import logger as loguru_logger

from src.container import Container


@contextmanager
def suppress_loguru():
    """
    Context manager pour desactiver les logs loguru pendant l'affichage Rich.

    Usage:
        with suppress_loguru():
            console.print(...)
    """
    loguru_logger.disable("src")
    try:
        yield
    finally:
        loguru_logger.enable("src")


def with_container(requires_db: bool = True):
    """
    Decorateur qui injecte un container initialise en premier argument.

    Args:
        requires_db: Si True (defaut), initialise la base de donnees.

    Usage:
        @with_container()
        async def my_command(container, ...):
            config = container.config()
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            container = Container()
            if requires_db:
                container.database.init()
            return await func(container, *args, **kwargs)
        return wrapper
    return decorator


def async_command(func):
    """
    Transforme une fonction async en commande sync via asyncio.run().

    Preserve les annotations Typer pour que les options/arguments soient
    correctement interpretes.

    Usage:
        @async_command
        @with_container()
        async def my_command(container, ...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        asyncio.run(func(*args, **kwargs))
    # Preserver les annotations Typer
    wrapper.__signature__ = inspect.signature(func)
    wrapper.__annotations__ = func.__annotations__
    return wrapper
