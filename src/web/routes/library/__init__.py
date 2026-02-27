"""
Package routes bibliothèque — navigation films et séries.

Regroupe les sous-modules : browse, detail, player, reassociate.
"""

from fastapi import APIRouter

from . import browse, delete, detail, player, reassociate, suggest, trash

router = APIRouter(prefix="/library")

router.include_router(browse.router)
router.include_router(suggest.router)
router.include_router(detail.router)
router.include_router(player.router)
router.include_router(reassociate.router)
router.include_router(delete.router)
router.include_router(trash.router)
