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
# Numéro seul, pour le bandeau où le nom de l'app est déjà affiché
templates.env.globals["app_version_number"] = get_version()


# Cache-buster pour les assets statiques (invalidé à chaque modif CSS ou JS)
def _asset_version() -> str:
    """Retourne le mtime le plus récent des CSS/JS pour busting du cache navigateur.

    Ne suivre que style.css laissait l'URL des scripts inchangée après une
    modification JS seule : le navigateur gardait l'ancien script en cache.
    """
    static = _WEB_DIR / "static"
    try:
        mtimes = [
            p.stat().st_mtime for p in static.rglob("*") if p.suffix in (".css", ".js")
        ]
    except OSError:
        return "0"
    return str(int(max(mtimes))) if mtimes else "0"


templates.env.globals["asset_version"] = _asset_version

# Profils lecteur accessibles dans tous les templates (sélecteur de profil + identité)
from ..player_profiles import load_profiles as _load_profiles  # noqa: E402

templates.env.globals["get_player_profiles"] = _load_profiles
