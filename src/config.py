"""
Application configuration using pydantic-settings.

Configuration is loaded from environment variables with CINEORG_ prefix,
and can optionally be provided via a .env file.

API keys (TMDB, TVDB) are optional - features are disabled if not provided.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support.

    All settings can be overridden via environment variables with CINEORG_ prefix.
    Example: CINEORG_LOG_LEVEL=DEBUG

    Paths are automatically expanded (~ -> home directory).
    """

    model_config = SettingsConfigDict(
        env_prefix="CINEORG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Paths (with ~ expansion)
    downloads_dir: Path = Field(default=Path("~/Downloads"))
    storage_dir: Path = Field(default=Path("~/Videos/storage"))
    video_dir: Path = Field(default=Path("~/Videos/video"))

    # Database
    database_url: str = Field(default="sqlite:///cineorg.db")

    # API Keys (OPTIONAL - API features disabled if not set)
    tmdb_api_key: Optional[str] = Field(default=None)
    tvdb_api_key: Optional[str] = Field(default=None)

    # Processing
    min_file_size_mb: int = Field(default=100, ge=1)
    max_files_per_subdir: int = Field(default=50, ge=1)
    match_score_threshold: int = Field(default=85, ge=0, le=100)

    # Logging (file + stderr, rotation 10MB, 5 files retention)
    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=Path("logs/cineorg.log"))
    log_rotation_size: str = Field(default="10 MB")
    log_retention_count: int = Field(default=5)

    @field_validator("downloads_dir", "storage_dir", "video_dir", "log_file", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        """Expand ~ to home directory in paths."""
        return Path(v).expanduser()

    @property
    def tmdb_enabled(self) -> bool:
        """Check if TMDB API is configured."""
        return self.tmdb_api_key is not None

    @property
    def tvdb_enabled(self) -> bool:
        """Check if TVDB API is configured."""
        return self.tvdb_api_key is not None
