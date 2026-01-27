"""
Implementations SQLModel des repositories.

Ce module contient les implementations concretes des interfaces repository
definies dans src/core/ports/repositories.py, utilisant SQLModel pour
la persistance SQLite.

Chaque repository :
- Herite de l'interface ABC correspondante du domaine
- Recoit une session SQLModel via injection de dependances
- Convertit entre entites de domaine (dataclass) et modeles DB (SQLModel)
"""

from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository,
)
from src.infrastructure.persistence.repositories.series_repository import (
    SQLModelSeriesRepository,
)
from src.infrastructure.persistence.repositories.episode_repository import (
    SQLModelEpisodeRepository,
)
from src.infrastructure.persistence.repositories.video_file_repository import (
    SQLModelVideoFileRepository,
)
from src.infrastructure.persistence.repositories.pending_validation_repository import (
    SQLModelPendingValidationRepository,
)

__all__ = [
    "SQLModelMovieRepository",
    "SQLModelSeriesRepository",
    "SQLModelEpisodeRepository",
    "SQLModelVideoFileRepository",
    "SQLModelPendingValidationRepository",
]
