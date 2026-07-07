"""Accès à l'état du partage Jellyfin actif."""

from datetime import datetime

from sqlmodel import Session, select

from src.infrastructure.persistence.models import ShareSessionModel


class ShareSessionRepository:
    """Gère l'unique ShareSessionModel actif."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(self) -> ShareSessionModel | None:
        statement = select(ShareSessionModel).where(ShareSessionModel.is_active == True)  # noqa: E712
        return self._session.exec(statement).first()

    def start(
        self, *, media_type: str, media_id: int, title: str, folder_name: str
    ) -> ShareSessionModel:
        model = ShareSessionModel(
            media_type=media_type,
            media_id=media_id,
            title=title,
            folder_name=folder_name,
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def touch_played(self, model: ShareSessionModel, when: datetime) -> None:
        model.last_played_at = when
        self._session.add(model)
        self._session.commit()

    def deactivate(self, model: ShareSessionModel) -> None:
        model.is_active = False
        self._session.add(model)
        self._session.commit()
