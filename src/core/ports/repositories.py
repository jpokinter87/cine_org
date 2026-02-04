"""
Interfaces ports pour les repositories.

Interfaces abstraites (ports) définissant les contrats pour la persistance des données.
Les implémentations (adaptateurs) fourniront les mécanismes de stockage concrets
(SQLite via SQLModel, en mémoire pour les tests, etc.).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core.entities.video import PendingValidation, VideoFile
from src.core.entities.media import Movie, Series, Episode


class IVideoFileRepository(ABC):
    """
    Interface de stockage des fichiers vidéo.

    Définit les opérations pour persister et récupérer les entités VideoFile.
    """

    @abstractmethod
    def get_by_id(self, video_id: str) -> Optional[VideoFile]:
        """Récupère un fichier vidéo par son ID."""
        ...

    @abstractmethod
    def get_by_path(self, path: Path) -> Optional[VideoFile]:
        """Récupère un fichier vidéo par son chemin."""
        ...

    @abstractmethod
    def get_by_hash(self, file_hash: str) -> Optional[VideoFile]:
        """Récupère un fichier vidéo par son hash de contenu."""
        ...

    @abstractmethod
    def save(self, video_file: VideoFile) -> VideoFile:
        """Sauvegarde un fichier vidéo (insertion ou mise à jour)."""
        ...

    @abstractmethod
    def delete(self, video_id: str) -> bool:
        """Supprime un fichier vidéo par ID. Retourne True si supprimé."""
        ...

    @abstractmethod
    def list_pending(self) -> list[PendingValidation]:
        """Liste tous les fichiers vidéo avec une validation en attente."""
        ...


class IMovieRepository(ABC):
    """
    Interface de stockage des métadonnées de films.

    Définit les opérations pour persister et récupérer les entités Movie.
    """

    @abstractmethod
    def get_by_id(self, movie_id: str) -> Optional[Movie]:
        """Récupère un film par son ID interne."""
        ...

    @abstractmethod
    def get_by_tmdb_id(self, tmdb_id: int) -> Optional[Movie]:
        """Récupère un film par son ID TMDB."""
        ...

    @abstractmethod
    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Movie]:
        """Recherche des films par titre, avec filtrage optionnel par année."""
        ...

    @abstractmethod
    def save(self, movie: Movie) -> Movie:
        """Sauvegarde un film (insertion ou mise à jour)."""
        ...

    @abstractmethod
    def list_without_ratings(self, limit: int = 100) -> list[Movie]:
        """Liste les films sans notes TMDB (vote_average ou vote_count null)."""
        ...

    @abstractmethod
    def list_without_imdb_id(self, limit: int = 100) -> list[Movie]:
        """Liste les films avec tmdb_id mais sans imdb_id."""
        ...


class ISeriesRepository(ABC):
    """
    Interface de stockage des métadonnées de séries.

    Définit les opérations pour persister et récupérer les entités Series.
    """

    @abstractmethod
    def get_by_id(self, series_id: str) -> Optional[Series]:
        """Récupère une série par son ID interne."""
        ...

    @abstractmethod
    def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Series]:
        """Récupère une série par son ID TVDB."""
        ...

    @abstractmethod
    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Series]:
        """Recherche des séries par titre, avec filtrage optionnel par année."""
        ...

    @abstractmethod
    def save(self, series: Series) -> Series:
        """Sauvegarde une série (insertion ou mise à jour)."""
        ...


class IEpisodeRepository(ABC):
    """
    Interface de stockage des métadonnées d'épisodes.

    Définit les opérations pour persister et récupérer les entités Episode.
    """

    @abstractmethod
    def get_by_id(self, episode_id: str) -> Optional[Episode]:
        """Récupère un épisode par son ID interne."""
        ...

    @abstractmethod
    def get_by_series(
        self,
        series_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[Episode]:
        """
        Récupère les épisodes d'une série.

        Args :
            series_id : L'ID de la série
            season : Filtre optionnel par numéro de saison
            episode : Filtre optionnel par numéro d'épisode (nécessite season)

        Retourne :
            Liste des épisodes correspondants
        """
        ...

    @abstractmethod
    def save(self, episode: Episode) -> Episode:
        """Sauvegarde un épisode (insertion ou mise à jour)."""
        ...
