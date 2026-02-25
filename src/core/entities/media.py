"""
Entités métadonnées média.

Entités représentant les films et séries TV avec leurs métadonnées
provenant des APIs externes (TMDB, TVDB).
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Movie:
    """
    Métadonnées d'un film depuis TMDB.

    Représente les informations enrichies d'un film récupérées depuis l'API The Movie Database.

    Attributs :
        id : ID interne base de données
        tmdb_id : ID The Movie Database
        title : Titre localisé (français pour cette application)
        original_title : Titre en langue originale
        year : Année de sortie
        genres : Tuple des noms de genre (français, dans l'ordre hiérarchique)
        duration_seconds : Durée en secondes
        overview : Résumé de l'intrigue
        poster_path : Chemin vers l'image poster sur le CDN TMDB
        vote_average : Note moyenne TMDB (0-10)
        vote_count : Nombre de votes sur TMDB
        imdb_id : ID IMDb (ex: "tt0499549")
        imdb_rating : Note moyenne IMDb (0-10)
        imdb_votes : Nombre de votes sur IMDb
        director : Realisateur principal
        cast : Tuple des acteurs principaux (3-5 premiers)
    """

    id: Optional[str] = None
    tmdb_id: Optional[int] = None
    title: str = ""
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_votes: Optional[int] = None
    director: Optional[str] = None
    cast: tuple[str, ...] = ()
    file_path: Optional[str] = None
    codec_video: Optional[str] = None
    codec_audio: Optional[str] = None
    resolution: Optional[str] = None
    languages: tuple[str, ...] = ()
    file_size_bytes: Optional[int] = None


@dataclass
class Series:
    """
    Métadonnées d'une série TV depuis TVDB.

    Représente les informations enrichies d'une série récupérées depuis l'API TheTVDB.

    Attributs :
        id : ID interne base de données
        tvdb_id : ID TheTVDB
        title : Titre localisé
        original_title : Titre en langue originale
        year : Année de première diffusion
        genres : Tuple des noms de genre
        overview : Description de la série
        poster_path : Chemin vers l'image poster
        vote_average : Note moyenne (0-10)
        vote_count : Nombre de votes
        imdb_id : ID IMDb (ex: "tt0903747")
        imdb_rating : Note moyenne IMDb (0-10)
        imdb_votes : Nombre de votes sur IMDb
        director : Createur(s) / showrunner principal
        cast : Tuple des acteurs principaux (3-5 premiers)
    """

    id: Optional[str] = None
    tvdb_id: Optional[int] = None
    tmdb_id: Optional[int] = None
    title: str = ""
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_votes: Optional[int] = None
    director: Optional[str] = None
    cast: tuple[str, ...] = ()


@dataclass
class Episode:
    """
    Épisode individuel d'une série TV.

    Attributs :
        id : ID interne base de données
        series_id : Référence vers la série parente
        season_number : Numéro de saison (commence à 1)
        episode_number : Numéro d'épisode dans la saison (commence à 1)
        title : Titre de l'épisode
        air_date : Date de première diffusion
        duration_seconds : Durée de l'épisode en secondes
        overview : Description de l'épisode
    """

    id: Optional[str] = None
    series_id: Optional[str] = None
    season_number: int = 0
    episode_number: int = 0
    title: str = ""
    air_date: Optional[date] = None
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
    file_path: Optional[str] = None
    codec_video: Optional[str] = None
    codec_audio: Optional[str] = None
    resolution: Optional[str] = None
    languages: tuple[str, ...] = ()
    file_size_bytes: Optional[int] = None
