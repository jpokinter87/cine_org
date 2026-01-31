"""
Configuration de l'application via pydantic-settings.

La configuration est chargée depuis les variables d'environnement avec le préfixe CINEORG_,
et peut optionnellement être fournie via un fichier .env.

Les clés API (TMDB, TVDB) sont optionnelles - les fonctionnalités sont désactivées si non fournies.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Trouver le fichier .env à la racine du projet (parent de src/)
_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Paramètres de l'application avec support des variables d'environnement.

    Tous les paramètres peuvent être surchargés via des variables d'environnement
    avec le préfixe CINEORG_.
    Exemple : CINEORG_LOG_LEVEL=DEBUG

    Les chemins sont automatiquement étendus (~ -> répertoire home).
    """

    model_config = SettingsConfigDict(
        env_prefix="CINEORG_",
        env_file=_ENV_FILE if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Chemins (avec expansion ~)
    downloads_dir: Path = Field(default=Path("~/Downloads"))
    storage_dir: Path = Field(default=Path("~/Videos/storage"))
    video_dir: Path = Field(default=Path("~/Videos/video"))

    # Base de données
    database_url: str = Field(default="sqlite:///cineorg.db")

    # Clés API (OPTIONNELLES - fonctionnalités API désactivées si non définies)
    tmdb_api_key: Optional[str] = Field(default=None)
    tvdb_api_key: Optional[str] = Field(default=None)

    # Traitement
    min_file_size_mb: int = Field(default=100, ge=1)
    max_files_per_subdir: int = Field(default=50, ge=1)
    match_score_threshold: int = Field(default=85, ge=0, le=100)

    # Logging (fichier + stderr, rotation 10MB, 5 fichiers de rétention)
    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=Path("logs/cineorg.log"))
    log_rotation_size: str = Field(default="10 MB")
    log_retention_count: int = Field(default=5)

    @field_validator("downloads_dir", "storage_dir", "video_dir", "log_file", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        """Étend ~ vers le répertoire home dans les chemins."""
        return Path(v).expanduser()

    @property
    def tmdb_enabled(self) -> bool:
        """Vérifie si l'API TMDB est configurée."""
        return self.tmdb_api_key is not None

    @property
    def tvdb_enabled(self) -> bool:
        """Vérifie si l'API TVDB est configurée."""
        return self.tvdb_api_key is not None
