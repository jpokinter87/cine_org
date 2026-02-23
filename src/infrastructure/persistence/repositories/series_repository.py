"""
Implementation SQLModel du repository Series.

Implemente l'interface ISeriesRepository pour la persistance des series TV
dans la base de donnees SQLite via SQLModel.
"""

import json
from typing import Optional

from sqlmodel import Session, select

from src.core.entities.media import Series
from src.core.ports.repositories import ISeriesRepository
from src.infrastructure.persistence.models import SeriesModel


class SQLModelSeriesRepository(ISeriesRepository):
    """
    Repository SQLModel pour les series TV.

    Implemente ISeriesRepository avec conversion bidirectionnelle
    entre l'entite Series (domaine) et SeriesModel (persistance).
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise le repository avec une session SQLModel.

        Args :
            session : Session SQLModel active pour les operations DB
        """
        self._session = session

    def _to_entity(self, model: SeriesModel) -> Series:
        """
        Convertit un modele DB en entite domaine.

        Args :
            model : Le modele SeriesModel depuis la DB

        Retourne :
            L'entite Series correspondante
        """
        genres_list = json.loads(model.genres_json) if model.genres_json else []
        cast_list = json.loads(model.cast_json) if model.cast_json else []
        return Series(
            id=str(model.id) if model.id else None,
            tvdb_id=model.tvdb_id,
            tmdb_id=model.tmdb_id,
            title=model.title,
            original_title=model.original_title,
            year=model.year,
            genres=tuple(genres_list),
            overview=model.overview,
            poster_path=model.poster_path,
            vote_average=model.vote_average,
            vote_count=model.vote_count,
            imdb_id=model.imdb_id,
            imdb_rating=model.imdb_rating,
            imdb_votes=model.imdb_votes,
            director=model.director,
            cast=tuple(cast_list),
        )

    def _to_model(self, entity: Series) -> SeriesModel:
        """
        Convertit une entite domaine en modele DB.

        Args :
            entity : L'entite Series du domaine

        Retourne :
            Le modele SeriesModel pour la persistance
        """
        model = SeriesModel(
            tvdb_id=entity.tvdb_id,
            tmdb_id=entity.tmdb_id,
            imdb_id=entity.imdb_id,
            title=entity.title,
            original_title=entity.original_title,
            year=entity.year,
            genres_json=json.dumps(list(entity.genres)) if entity.genres else None,
            overview=entity.overview,
            poster_path=entity.poster_path,
            vote_average=entity.vote_average,
            vote_count=entity.vote_count,
            imdb_rating=entity.imdb_rating,
            imdb_votes=entity.imdb_votes,
            director=entity.director,
            cast_json=json.dumps(list(entity.cast)) if entity.cast else None,
        )
        if entity.id:
            model.id = int(entity.id)
        return model

    def get_by_id(self, series_id: str) -> Optional[Series]:
        """Recupere une serie par son ID interne."""
        statement = select(SeriesModel).where(SeriesModel.id == int(series_id))
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Series]:
        """Recupere une serie par son ID TVDB."""
        statement = select(SeriesModel).where(SeriesModel.tvdb_id == tvdb_id)
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Series]:
        """Recherche des series par titre, avec filtrage optionnel par annee."""
        statement = select(SeriesModel).where(SeriesModel.title.contains(title))
        if year is not None:
            statement = statement.where(SeriesModel.year == year)
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def save(self, series: Series) -> Series:
        """Sauvegarde une serie (insertion ou mise a jour)."""
        # Verifier si la serie existe deja (par ID ou tvdb_id)
        existing = None
        if series.id:
            existing = self._session.get(SeriesModel, int(series.id))
        elif series.tvdb_id:
            statement = select(SeriesModel).where(SeriesModel.tvdb_id == series.tvdb_id)
            existing = self._session.exec(statement).first()

        if existing:
            # Mise a jour
            existing.tmdb_id = series.tmdb_id
            existing.title = series.title
            existing.original_title = series.original_title
            existing.year = series.year
            existing.genres_json = (
                json.dumps(list(series.genres)) if series.genres else None
            )
            existing.overview = series.overview
            existing.poster_path = series.poster_path
            existing.vote_average = series.vote_average
            existing.vote_count = series.vote_count
            existing.imdb_id = series.imdb_id
            existing.imdb_rating = series.imdb_rating
            existing.imdb_votes = series.imdb_votes
            existing.director = series.director
            existing.cast_json = (
                json.dumps(list(series.cast)) if series.cast else None
            )
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return self._to_entity(existing)
        else:
            # Insertion
            model = self._to_model(series)
            self._session.add(model)
            self._session.commit()
            self._session.refresh(model)
            return self._to_entity(model)
