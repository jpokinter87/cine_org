"""
Application FastAPI de CineOrg.

Initialise l'application web avec le Container DI existant,
configure les fichiers statiques et monte les routes.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ..container import Container
from ..services.share.monitor import share_monitor_loop
from .routes.config import router as config_router
from .routes.home import router as home_router
from .routes.maintenance import router as maintenance_router
from .routes.library import router as library_router
from .routes.duplicates import router as duplicates_router
from .routes.quality import router as quality_router
from .routes.share import router as share_router
from .routes.transfer import router as transfer_router
from .routes.validation import router as validation_router
from .routes.workflow import router as workflow_router

_WEB_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise le Container DI, lance la surveillance du partage, nettoie à l'arrêt.

    La garde ``if getattr(app.state, "container", None) is None`` préserve
    un container déjà injecté (ex. mock de test) sans écraser le vrai Container.
    """
    if getattr(app.state, "container", None) is None:
        container = Container()
        container.database.init()
        app.state.container = container
    monitor_task = asyncio.create_task(share_monitor_loop(app.state.container))
    app.state.share_monitor_task = monitor_task
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        # Ferme proprement le client HTTP Jellyfin (best-effort au shutdown).
        try:
            await app.state.container.jellyfin_client().close()
        except Exception as exc:  # container mocké en test / client déjà fermé
            logger.debug("Fermeture du client Jellyfin ignorée : {}", exc)


app = FastAPI(title="CineOrg", lifespan=lifespan)

# Fichiers statiques
app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

# Routes
app.include_router(home_router)
app.include_router(validation_router)
app.include_router(workflow_router)
app.include_router(library_router)
app.include_router(transfer_router)
app.include_router(quality_router)
app.include_router(duplicates_router)
app.include_router(config_router)
app.include_router(maintenance_router)
app.include_router(share_router)
