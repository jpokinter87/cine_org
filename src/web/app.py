"""
Application FastAPI de CineOrg.

Initialise l'application web avec le Container DI existant,
configure les fichiers statiques et monte les routes.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..container import Container
from .routes.config import router as config_router
from .routes.home import router as home_router
from .routes.maintenance import router as maintenance_router
from .routes.library import router as library_router
from .routes.quality import router as quality_router
from .routes.transfer import router as transfer_router
from .routes.validation import router as validation_router
from .routes.workflow import router as workflow_router

_WEB_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise le Container DI au démarrage et le ferme à l'arrêt."""
    container = Container()
    container.database.init()
    app.state.container = container
    yield


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
app.include_router(config_router)
app.include_router(maintenance_router)
