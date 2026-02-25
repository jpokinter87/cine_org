"""
Implementation SQLModel du repository Movie.

Implemente l'interface IMovieRepository pour la persistance des films
dans la base de donnees SQLite via SQLModel.
"""

import json
from typing import Optional

from sqlmodel import Session, select

from src.core.entities.media import Movie
from src.core.ports.repositories import IMovieRepository
from src.infrastructure.persistence.models import MovieModel


class SQLModelMovieRepository(IMovieRepository):
    """
    Repository SQLModel pour les films.

    Implemente IMovieRepository avec conversion bidirectionnelle
    entre l'entite Movie (domaine) et MovieModel (persistance).
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise le repository avec une session SQLModel.

        Args :
            session : Session SQLModel active pour les operations DB
        """
        self._session = session

    def _to_entity(self, model: MovieModel) -> Movie:
        """
        Convertit un modele DB en entite domaine.

        Args :
            model : Le modele MovieModel depuis la DB

        Retourne :
            L'entite Movie correspondante
        """
        genres_list = json.loads(model.genres_json) if model.genres_json else []
        cast_list = json.loads(model.cast_json) if model.cast_json else []
        languages_list = json.loads(model.languages_json) if model.languages_json else []
        return Movie(
            id=str(model.id) if model.id else None,
            tmdb_id=model.tmdb_id,
            title=model.title,
            original_title=model.original_title,
            year=model.year,
            genres=tuple(genres_list),
            duration_seconds=model.duration_seconds,
            overview=model.overview,
            poster_path=model.poster_path,
            vote_average=model.vote_average,
            vote_count=model.vote_count,
            imdb_id=model.imdb_id,
            imdb_rating=model.imdb_rating,
            imdb_votes=model.imdb_votes,
            director=model.director,
            cast=tuple(cast_list),
            file_path=model.file_path,
            codec_video=model.codec_video,
            codec_audio=model.codec_audio,
            resolution=model.resolution,
            languages=tuple(languages_list),
            file_size_bytes=model.file_size_bytes,
        )

    def _to_model(self, entity: Movie) -> MovieModel:
        """
        Convertit une entite domaine en modele DB.

        Args :
            entity : L'entite Movie du domaine

        Retourne :
            Le modele MovieModel pour la persistance
        """
        model = MovieModel(
            tmdb_id=entity.tmdb_id,
            imdb_id=entity.imdb_id,
            title=entity.title,
            original_title=entity.original_title,
            year=entity.year,
            genres_json=json.dumps(list(entity.genres)) if entity.genres else None,
            duration_seconds=entity.duration_seconds,
            overview=entity.overview,
            poster_path=entity.poster_path,
            vote_average=entity.vote_average,
            vote_count=entity.vote_count,
            imdb_rating=entity.imdb_rating,
            imdb_votes=entity.imdb_votes,
            director=entity.director,
            cast_json=json.dumps(list(entity.cast)) if entity.cast else None,
            file_path=entity.file_path,
            codec_video=entity.codec_video,
            codec_audio=entity.codec_audio,
            resolution=entity.resolution,
            languages_json=json.dumps(list(entity.languages)) if entity.languages else None,
            file_size_bytes=entity.file_size_bytes,
        )
        if entity.id:
            model.id = int(entity.id)
        return model

    def get_by_id(self, movie_id: str) -> Optional[Movie]:
        """Recupere un film par son ID interne."""
        statement = select(MovieModel).where(MovieModel.id == int(movie_id))
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_tmdb_id(self, tmdb_id: int) -> Optional[Movie]:
        """Recupere un film par son ID TMDB."""
        statement = select(MovieModel).where(MovieModel.tmdb_id == tmdb_id)
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Movie]:
        """Recherche des films par titre, avec filtrage optionnel par annee."""
        statement = select(MovieModel).where(MovieModel.title.contains(title))
        if year is not None:
            statement = statement.where(MovieModel.year == year)
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def list_without_ratings(self, limit: int = 100) -> list[Movie]:
        """Liste les films sans notes TMDB (vote_average ou vote_count null)."""
        from sqlalchemy import or_

        statement = (
            select(MovieModel)
            .where(
                or_(
                    MovieModel.vote_average.is_(None),
                    MovieModel.vote_count.is_(None),
                )
            )
            .where(MovieModel.tmdb_id.isnot(None))  # Doit avoir un tmdb_id
            .limit(limit)
        )
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def list_without_imdb_id(self, limit: int = 100) -> list[Movie]:
        """Liste les films avec tmdb_id mais sans imdb_id."""
        statement = (
            select(MovieModel)
            .where(MovieModel.tmdb_id.isnot(None))
            .where(MovieModel.imdb_id.is_(None))
            .limit(limit)
        )
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def save(self, movie: Movie) -> Movie:
        """Sauvegarde un film (insertion ou mise a jour)."""
        # Nettoyage preventif des titres (caractères invisibles)
        from src.utils.helpers import clean_title

        if movie.title:
            movie.title = clean_title(movie.title)
        if movie.original_title:
            movie.original_title = clean_title(movie.original_title)

        # Verifier si le film existe deja (par ID ou tmdb_id)
        existing = None
        if movie.id:
            existing = self._session.get(MovieModel, int(movie.id))
        elif movie.tmdb_id:
            statement = select(MovieModel).where(MovieModel.tmdb_id == movie.tmdb_id)
            existing = self._session.exec(statement).first()

        if existing:
            # Mise a jour
            existing.title = movie.title
            existing.original_title = movie.original_title
            existing.year = movie.year
            existing.genres_json = (
                json.dumps(list(movie.genres)) if movie.genres else None
            )
            existing.duration_seconds = movie.duration_seconds
            existing.overview = movie.overview
            existing.poster_path = movie.poster_path
            existing.vote_average = movie.vote_average
            existing.vote_count = movie.vote_count
            existing.imdb_id = movie.imdb_id
            existing.imdb_rating = movie.imdb_rating
            existing.imdb_votes = movie.imdb_votes
            existing.director = movie.director
            existing.cast_json = (
                json.dumps(list(movie.cast)) if movie.cast else None
            )
            if movie.file_path is not None:
                existing.file_path = movie.file_path
            if movie.codec_video is not None:
                existing.codec_video = movie.codec_video
            if movie.codec_audio is not None:
                existing.codec_audio = movie.codec_audio
            if movie.resolution is not None:
                existing.resolution = movie.resolution
            if movie.languages:
                existing.languages_json = json.dumps(list(movie.languages))
            if movie.file_size_bytes is not None:
                existing.file_size_bytes = movie.file_size_bytes
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return self._to_entity(existing)
        else:
            # Insertion
            model = self._to_model(movie)
            self._session.add(model)
            self._session.commit()
            self._session.refresh(model)
            return self._to_entity(model)
