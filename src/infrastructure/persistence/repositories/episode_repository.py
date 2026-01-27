"""
Implementation SQLModel du repository Episode.

Implemente l'interface IEpisodeRepository pour la persistance des episodes
dans la base de donnees SQLite via SQLModel.
"""

from typing import Optional

from sqlmodel import Session, select

from src.core.entities.media import Episode
from src.core.ports.repositories import IEpisodeRepository
from src.infrastructure.persistence.models import EpisodeModel


class SQLModelEpisodeRepository(IEpisodeRepository):
    """
    Repository SQLModel pour les episodes de series.

    Implemente IEpisodeRepository avec conversion bidirectionnelle
    entre l'entite Episode (domaine) et EpisodeModel (persistance).
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise le repository avec une session SQLModel.

        Args :
            session : Session SQLModel active pour les operations DB
        """
        self._session = session

    def _to_entity(self, model: EpisodeModel) -> Episode:
        """
        Convertit un modele DB en entite domaine.

        Args :
            model : Le modele EpisodeModel depuis la DB

        Retourne :
            L'entite Episode correspondante
        """
        return Episode(
            id=str(model.id) if model.id else None,
            series_id=str(model.series_id) if model.series_id else None,
            season_number=model.season_number,
            episode_number=model.episode_number,
            title=model.title,
            air_date=model.air_date,
            duration_seconds=model.duration_seconds,
            overview=model.overview,
        )

    def _to_model(self, entity: Episode) -> EpisodeModel:
        """
        Convertit une entite domaine en modele DB.

        Args :
            entity : L'entite Episode du domaine

        Retourne :
            Le modele EpisodeModel pour la persistance
        """
        model = EpisodeModel(
            series_id=int(entity.series_id) if entity.series_id else 0,
            season_number=entity.season_number,
            episode_number=entity.episode_number,
            title=entity.title,
            air_date=entity.air_date,
            duration_seconds=entity.duration_seconds,
            overview=entity.overview,
        )
        if entity.id:
            model.id = int(entity.id)
        return model

    def get_by_id(self, episode_id: str) -> Optional[Episode]:
        """Recupere un episode par son ID interne."""
        statement = select(EpisodeModel).where(EpisodeModel.id == int(episode_id))
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_series(
        self,
        series_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[Episode]:
        """
        Recupere les episodes d'une serie.

        Args :
            series_id : L'ID de la serie
            season : Filtre optionnel par numero de saison
            episode : Filtre optionnel par numero d'episode (necessite season)

        Retourne :
            Liste des episodes correspondants
        """
        statement = select(EpisodeModel).where(
            EpisodeModel.series_id == int(series_id)
        )
        if season is not None:
            statement = statement.where(EpisodeModel.season_number == season)
            if episode is not None:
                statement = statement.where(EpisodeModel.episode_number == episode)
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def save(self, episode: Episode) -> Episode:
        """Sauvegarde un episode (insertion ou mise a jour)."""
        # Verifier si l'episode existe deja par ID
        existing = None
        if episode.id:
            existing = self._session.get(EpisodeModel, int(episode.id))

        if existing:
            # Mise a jour
            existing.series_id = int(episode.series_id) if episode.series_id else 0
            existing.season_number = episode.season_number
            existing.episode_number = episode.episode_number
            existing.title = episode.title
            existing.air_date = episode.air_date
            existing.duration_seconds = episode.duration_seconds
            existing.overview = episode.overview
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return self._to_entity(existing)
        else:
            # Insertion
            model = self._to_model(episode)
            self._session.add(model)
            self._session.commit()
            self._session.refresh(model)
            return self._to_entity(model)
