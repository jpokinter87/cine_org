"""
Dépendances partagées de l'application web.

Fournit les templates Jinja2 utilisées par toutes les routes.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from ..version import get_version

_WEB_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=_WEB_DIR / "templates")

# Version dynamique (source unique : src/version.py) — dispo dans tous les templates
templates.env.globals["app_version"] = f"CineOrg v{get_version()}"

# Cache-buster pour les assets statiques (invalidé à chaque modif de style.css)
def _asset_version() -> str:
    """Retourne le mtime du style.css pour busting du cache navigateur."""
    try:
        return str(int((_WEB_DIR / "static" / "css" / "style.css").stat().st_mtime))
    except OSError:
        return "0"

templates.env.globals["asset_version"] = _asset_version

# Profils lecteur accessibles dans tous les templates (sélecteur de profil + identité)
from ..player_profiles import (  # noqa: E402
    get_personal_profiles as _personal_profiles,
    load_profiles as _load_profiles,
)

templates.env.globals["get_player_profiles"] = _load_profiles
templates.env.globals["get_personal_profiles"] = _personal_profiles
