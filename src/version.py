"""Source unique de vérité pour la version de l'application.

La version est stockée dans `[project].version` de `pyproject.toml`. Ce module
la lit dynamiquement afin que le web (footer) et le CLI affichent toujours la
même valeur, sans duplication.
"""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def get_version() -> str:
    """Retourne la version courante lue depuis pyproject.toml."""
    with open(_PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["version"]
