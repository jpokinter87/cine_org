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
from .routes.home import router as home_router
from .routes.validation import router as validation_router

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
