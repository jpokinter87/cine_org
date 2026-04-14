"""
Dépendances partagées de l'application web.

Fournit les templates Jinja2 utilisées par toutes les routes.
"""

import tomllib
from pathlib import Path

from fastapi.templating import Jinja2Templates

_WEB_DIR = Path(__file__).parent
_PROJECT_ROOT = _WEB_DIR.parent.parent

templates = Jinja2Templates(directory=_WEB_DIR / "templates")

# Version dynamique lue depuis pyproject.toml — disponible dans tous les templates
with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
    _pyproject = tomllib.load(f)
templates.env.globals["app_version"] = f"CineOrg v{_pyproject['project']['version']}"

# Cache-buster pour les assets statiques (invalidé à chaque modif de style.css)
def _asset_version() -> str:
    """Retourne le mtime du style.css pour busting du cache navigateur."""
    try:
        return str(int((_WEB_DIR / "static" / "css" / "style.css").stat().st_mtime))
    except OSError:
        return "0"

templates.env.globals["asset_version"] = _asset_version

# Profils lecteur accessibles dans tous les templates (pour le sélecteur de profil)
from ..player_profiles import load_profiles as _load_profiles  # noqa: E402

templates.env.globals["get_player_profiles"] = _load_profiles
