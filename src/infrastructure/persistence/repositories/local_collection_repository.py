"""Repository SQLModel pour ``LocalCollection``.

CRUD minimal + listing avec compteur de films associés. Pas d'interface
abstraite ici — la collection locale est un détail de persistance peu sollicité
hors du service P4 (suggester) et de la CLI ``collections``.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from src.core.entities.local_collection import LocalCollection
from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel


@dataclass(frozen=True)
class LocalCollectionWithCount:
    """Collection + nombre de films associés (pour la commande ``list``)."""

    collection: LocalCollection
    movie_count: int


class SQLModelLocalCollectionRepository:
    """Implémentation SQLModel du repository ``LocalCollection``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _to_entity(self, model: LocalCollectionModel) -> LocalCollection:
        return LocalCollection(
            id=model.id,
            name=model.name,
            description=model.description,
            created_at=model.created_at,
        )

    def save(self, entity: LocalCollection) -> LocalCollection:
        if entity.id is not None:
            existing = self._session.get(LocalCollectionModel, entity.id)
            if existing is not None:
                existing.name = entity.name
                existing.description = entity.description
                self._session.add(existing)
                self._session.commit()
                self._session.refresh(existing)
                return self._to_entity(existing)

        model = LocalCollectionModel(
            name=entity.name,
            description=entity.description,
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return self._to_entity(model)

    def get_by_id(self, collection_id: int) -> Optional[LocalCollection]:
        model = self._session.get(LocalCollectionModel, collection_id)
        return self._to_entity(model) if model else None

    def get_by_name(self, name: str) -> Optional[LocalCollection]:
        stmt = select(LocalCollectionModel).where(LocalCollectionModel.name == name)
        model = self._session.exec(stmt).first()
        return self._to_entity(model) if model else None

    def list_all(self) -> list[LocalCollection]:
        stmt = select(LocalCollectionModel).order_by(LocalCollectionModel.name)
        return [self._to_entity(m) for m in self._session.exec(stmt).all()]

    def list_with_movie_counts(self) -> list[LocalCollectionWithCount]:
        """Liste toutes les collections + nombre de films associés (gauche)."""
        stmt = (
            select(
                LocalCollectionModel,
                func.count(MovieModel.id).label("movie_count"),
            )
            .outerjoin(
                MovieModel,
                MovieModel.local_collection_id == LocalCollectionModel.id,
            )
            .group_by(LocalCollectionModel.id)
            .order_by(LocalCollectionModel.name)
        )
        results: list[LocalCollectionWithCount] = []
        for model, count in self._session.exec(stmt).all():
            results.append(
                LocalCollectionWithCount(
                    collection=self._to_entity(model),
                    movie_count=int(count),
                )
            )
        return results
