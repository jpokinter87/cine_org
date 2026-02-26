"""
Modeles SQLModel pour la base de donnees CineOrg.

Ces modeles representent les tables de la base de donnees SQLite.
Ils sont distincts des entites de domaine (dataclass dans core/entities/)
selon l'architecture hexagonale.

Tables:
- movies: Films avec metadonnees TMDB
- series: Series TV avec metadonnees TVDB
- episodes: Episodes de series
- video_files: Fichiers video scannes
- pending_validations: Validations en attente de confirmation utilisateur
- trash: Corbeille pour restauration (soft delete)

Les champs JSON (*_json) permettent de stocker des listes (genres, langues)
de maniere serialisee dans SQLite.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Field, Index, SQLModel


class MovieModel(SQLModel, table=True):
    """
    Modele representant un film dans la base de donnees.

    Les metadonnees proviennent de TMDB et des fichiers locaux.
    Les champs *_json stockent des listes serialisees en JSON.
    """

    __tablename__ = "movies"

    id: int | None = Field(default=None, primary_key=True)
    tmdb_id: int | None = Field(default=None, index=True)
    imdb_id: str | None = Field(default=None, index=True)
    title: str = Field(index=True)
    original_title: str | None = None
    year: int | None = None
    genres_json: str | None = None  # JSON: ["Action", "Science-Fiction"]
    duration_seconds: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    file_path: str | None = Field(default=None, index=True)
    file_hash: str | None = Field(default=None, index=True)
    codec_video: str | None = None
    codec_audio: str | None = None
    resolution: str | None = None  # ex: "1920x1080"
    languages_json: str | None = None  # JSON: ["fr", "en"]
    file_size_bytes: int | None = None
    vote_average: float | None = None  # Note moyenne TMDB (0-10)
    vote_count: int | None = None  # Nombre de votes sur TMDB
    imdb_rating: float | None = None  # Note moyenne IMDb (0-10)
    imdb_votes: int | None = None  # Nombre de votes sur IMDb
    director: str | None = None  # Realisateur principal
    cast_json: str | None = None  # JSON: ["Acteur 1", "Acteur 2", ...]
    watched: bool = Field(default=False, index=True)  # Film deja vu
    personal_rating: Optional[int] = Field(default=None)  # Note personnelle 1-5
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def genres(self) -> list[str]:
        """Retourne les genres deserialises."""
        if self.genres_json:
            return json.loads(self.genres_json)
        return []

    @genres.setter
    def genres(self, value: list[str]) -> None:
        """Serialise les genres en JSON."""
        self.genres_json = json.dumps(value)

    @property
    def languages(self) -> list[str]:
        """Retourne les langues deserialisees."""
        if self.languages_json:
            return json.loads(self.languages_json)
        return []

    @languages.setter
    def languages(self, value: list[str]) -> None:
        """Serialise les langues en JSON."""
        self.languages_json = json.dumps(value)

    @property
    def cast(self) -> list[str]:
        """Retourne les acteurs deserialises."""
        if self.cast_json:
            return json.loads(self.cast_json)
        return []

    @cast.setter
    def cast(self, value: list[str]) -> None:
        """Serialise les acteurs en JSON."""
        self.cast_json = json.dumps(value)


class SeriesModel(SQLModel, table=True):
    """
    Modele representant une serie TV dans la base de donnees.

    Les metadonnees proviennent de TVDB.
    """

    __tablename__ = "series"

    id: int | None = Field(default=None, primary_key=True)
    tvdb_id: int | None = Field(default=None, index=True)
    tmdb_id: int | None = Field(default=None, index=True)
    imdb_id: str | None = Field(default=None, index=True)
    title: str = Field(index=True)
    original_title: str | None = None
    year: int | None = None
    genres_json: str | None = None
    overview: str | None = None
    poster_path: str | None = None
    vote_average: float | None = None  # Note moyenne (0-10)
    vote_count: int | None = None  # Nombre de votes
    imdb_rating: float | None = None  # Note moyenne IMDb (0-10)
    imdb_votes: int | None = None  # Nombre de votes sur IMDb
    director: str | None = None  # Createur(s) / showrunner principal
    cast_json: str | None = None  # JSON: ["Acteur 1", "Acteur 2", ...]
    watched: bool = Field(default=False, index=True)  # Serie deja vue
    personal_rating: Optional[int] = Field(default=None)  # Note personnelle 1-5
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def genres(self) -> list[str]:
        """Retourne les genres deserialises."""
        if self.genres_json:
            return json.loads(self.genres_json)
        return []

    @genres.setter
    def genres(self, value: list[str]) -> None:
        """Serialise les genres en JSON."""
        self.genres_json = json.dumps(value)

    @property
    def cast(self) -> list[str]:
        """Retourne les acteurs deserialises."""
        if self.cast_json:
            return json.loads(self.cast_json)
        return []

    @cast.setter
    def cast(self, value: list[str]) -> None:
        """Serialise les acteurs en JSON."""
        self.cast_json = json.dumps(value)


class EpisodeModel(SQLModel, table=True):
    """
    Modele representant un episode de serie TV.

    Lie a une serie via series_id (foreign key).
    """

    __tablename__ = "episodes"
    __table_args__ = (
        Index("ix_episodes_series_season_episode", "series_id", "season_number", "episode_number"),
    )

    id: int | None = Field(default=None, primary_key=True)
    series_id: int = Field(foreign_key="series.id", index=True)
    season_number: int
    episode_number: int
    title: str
    air_date: date | None = None
    duration_seconds: int | None = None
    overview: str | None = None
    file_path: str | None = Field(default=None, index=True)
    file_hash: str | None = Field(default=None, index=True)
    codec_video: str | None = None
    codec_audio: str | None = None
    resolution: str | None = None
    languages_json: str | None = None
    file_size_bytes: int | None = None
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def languages(self) -> list[str]:
        """Retourne les langues deserialisees."""
        if self.languages_json:
            return json.loads(self.languages_json)
        return []

    @languages.setter
    def languages(self, value: list[str]) -> None:
        """Serialise les langues en JSON."""
        self.languages_json = json.dumps(value)


class VideoFileModel(SQLModel, table=True):
    """
    Modele representant un fichier video scanne.

    Contient les informations techniques extraites du fichier
    avant identification via API.
    """

    __tablename__ = "video_files"

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True)  # Chemin du fichier physique (storage)
    symlink_path: str | None = Field(default=None, index=True)  # Chemin du symlink (video)
    filename: str
    file_hash: str | None = Field(default=None, index=True)
    size_bytes: int = 0
    codec_video: str | None = None
    codec_audio: str | None = None
    resolution_width: int | None = None
    resolution_height: int | None = None
    duration_seconds: int | None = None
    languages_json: str | None = None
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def languages(self) -> list[str]:
        """Retourne les langues deserialisees."""
        if self.languages_json:
            return json.loads(self.languages_json)
        return []

    @languages.setter
    def languages(self, value: list[str]) -> None:
        """Serialise les langues en JSON."""
        self.languages_json = json.dumps(value)


class PendingValidationModel(SQLModel, table=True):
    """
    Modele representant une validation en attente.

    Stocke les candidats API pour un fichier video non encore
    valide (automatiquement ou manuellement).
    """

    __tablename__ = "pending_validations"

    id: int | None = Field(default=None, primary_key=True)
    video_file_id: int = Field(foreign_key="video_files.id", index=True)
    candidates_json: str | None = None  # JSON: top 5 candidats API
    auto_validated: bool = False
    validation_status: str = "pending"  # pending, validated, rejected
    selected_candidate_id: str | None = None  # tmdb_id ou tvdb_id selectionne
    created_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def candidates(self) -> list[dict[str, Any]]:
        """Retourne les candidats deserialises."""
        if self.candidates_json:
            return json.loads(self.candidates_json)
        return []

    @candidates.setter
    def candidates(self, value: list[dict[str, Any]]) -> None:
        """Serialise les candidats en JSON."""
        self.candidates_json = json.dumps(value)


class IMDbRatingModel(SQLModel, table=True):
    """
    Modele representant une note IMDb dans le cache local.

    Stocke les notes IMDb importees depuis les datasets publics.
    Permet de faire des lookups locaux sans appels API.
    """

    __tablename__ = "imdb_ratings"

    tconst: str = Field(primary_key=True)  # ID IMDb ex: "tt0499549"
    average_rating: float
    num_votes: int
    last_updated: date | None = Field(default_factory=date.today)


class TrashModel(SQLModel, table=True):
    """
    Modele representant un element dans la corbeille.

    Permet la restauration d'elements supprimes (soft delete).
    Les metadonnees completes sont serialisees en JSON.
    """

    __tablename__ = "trash"

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str  # movie, series, episode, video_file
    original_id: int  # ID dans la table source avant suppression
    metadata_json: str  # Toutes les metadonnees pour restauration
    deleted_at: datetime = Field(default_factory=datetime.utcnow)
    deletion_reason: str | None = None

    @property
    def entity_metadata(self) -> dict[str, Any]:
        """Retourne les metadonnees deserialisees."""
        if self.metadata_json:
            return json.loads(self.metadata_json)
        return {}

    @entity_metadata.setter
    def entity_metadata(self, value: dict[str, Any]) -> None:
        """Serialise les metadonnees en JSON."""
        self.metadata_json = json.dumps(value)


class ConfirmedAssociationModel(SQLModel, table=True):
    """
    Associations TMDB confirmées manuellement par l'utilisateur.

    Permet d'exclure des résultats du scan de détection d'erreurs
    les entités dont l'association est correcte malgré les heuristiques.
    """

    __tablename__ = "confirmed_associations"

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str  # "movie" | "series"
    entity_id: int = Field(index=True)
    confirmed_at: datetime = Field(default_factory=datetime.utcnow)
