"""
Implementation SQLModel du repository Trash (corbeille).

Gère le stockage et la restauration des éléments supprimés
via la table trash avec métadonnées JSON sérialisées.
"""

from sqlmodel import Session, select

from src.infrastructure.persistence.models import TrashModel


class SQLModelTrashRepository:
    """Repository SQLModel pour la corbeille."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, trash: TrashModel) -> TrashModel:
        """Persiste un élément en corbeille."""
        self._session.add(trash)
        self._session.commit()
        self._session.refresh(trash)
        return trash

    def list_all(self) -> list[TrashModel]:
        """Retourne tous les éléments de la corbeille, du plus récent au plus ancien."""
        stmt = select(TrashModel).order_by(TrashModel.deleted_at.desc())
        return list(self._session.exec(stmt).all())

    def get_by_id(self, trash_id: int) -> TrashModel | None:
        """Récupère un élément de la corbeille par son ID."""
        return self._session.get(TrashModel, trash_id)

    def delete(self, trash_id: int) -> bool:
        """Supprime une entrée de la corbeille. Retourne True si supprimé."""
        trash = self._session.get(TrashModel, trash_id)
        if trash:
            self._session.delete(trash)
            self._session.commit()
            return True
        return False

    def delete_all(self) -> int:
        """Vide la corbeille. Retourne le nombre d'éléments supprimés."""
        items = self.list_all()
        count = len(items)
        for item in items:
            self._session.delete(item)
        self._session.commit()
        return count

    def count(self) -> int:
        """Retourne le nombre d'éléments dans la corbeille."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(TrashModel)
        return self._session.exec(stmt).one()
