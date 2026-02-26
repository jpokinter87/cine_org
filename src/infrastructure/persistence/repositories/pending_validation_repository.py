"""
Implementation SQLModel du repository PendingValidation.

Repository concret pour la gestion des validations en attente
dans la base de donnees SQLite via SQLModel.
"""

import json
from typing import Optional

from sqlmodel import Session, select

from src.core.entities.video import PendingValidation, ValidationStatus
from src.infrastructure.persistence.models import PendingValidationModel, VideoFileModel
from src.infrastructure.persistence.repositories.video_file_repository import (
    SQLModelVideoFileRepository,
)


class SQLModelPendingValidationRepository:
    """
    Repository SQLModel pour les validations en attente.

    Gere la persistance des PendingValidation avec conversion
    bidirectionnelle entre entite et modele.
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise le repository avec une session SQLModel.

        Args :
            session : Session SQLModel active pour les operations DB
        """
        self._session = session
        self._video_file_repo = SQLModelVideoFileRepository(session)

    def _to_entity(self, model: PendingValidationModel) -> PendingValidation:
        """
        Convertit un modele DB en entite domaine.

        Args :
            model : Le modele PendingValidationModel depuis la DB

        Retourne :
            L'entite PendingValidation correspondante
        """
        # Recuperer le VideoFile associe
        video_file = None
        if model.video_file_id:
            vf_model = self._session.get(VideoFileModel, model.video_file_id)
            if vf_model:
                video_file = self._video_file_repo._to_entity(vf_model)

        candidates = json.loads(model.candidates_json) if model.candidates_json else []

        return PendingValidation(
            id=str(model.id) if model.id else None,
            video_file=video_file,
            candidates=candidates,
            auto_validated=model.auto_validated,
            validation_status=ValidationStatus(model.validation_status),
            selected_candidate_id=model.selected_candidate_id,
            created_at=model.created_at,
        )

    def _to_model(
        self, entity: PendingValidation, video_file_id: int
    ) -> PendingValidationModel:
        """
        Convertit une entite domaine en modele DB.

        Args :
            entity : L'entite PendingValidation du domaine
            video_file_id : ID du VideoFile associe dans la DB

        Retourne :
            Le modele PendingValidationModel pour la persistance
        """
        model = PendingValidationModel(
            video_file_id=video_file_id,
            candidates_json=json.dumps(entity.candidates)
            if entity.candidates
            else None,
            auto_validated=entity.auto_validated,
            validation_status=entity.validation_status.value,
            selected_candidate_id=entity.selected_candidate_id,
        )
        if entity.id:
            model.id = int(entity.id)
        return model

    def get_by_id(self, validation_id: str) -> Optional[PendingValidation]:
        """Recupere une validation par son ID."""
        statement = select(PendingValidationModel).where(
            PendingValidationModel.id == int(validation_id)
        )
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_video_file_id(self, video_file_id: str) -> Optional[PendingValidation]:
        """Recupere une validation par l'ID du fichier video associe."""
        statement = select(PendingValidationModel).where(
            PendingValidationModel.video_file_id == int(video_file_id)
        )
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def list_pending(self) -> list[PendingValidation]:
        """Liste toutes les validations en statut 'pending'."""
        statement = select(PendingValidationModel).where(
            PendingValidationModel.validation_status == "pending"
        )
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def list_validated(self, limit: int = 0) -> list[PendingValidation]:
        """Liste les validations validees avec un selected_candidate_id.

        Args:
            limit: Nombre max de resultats (0 = illimite)
        """
        statement = (
            select(PendingValidationModel)
            .where(PendingValidationModel.validation_status == "validated")
            .where(PendingValidationModel.selected_candidate_id.isnot(None))
        )
        if limit > 0:
            statement = statement.limit(limit)
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def list_auto_validated(self) -> list[PendingValidation]:
        """Liste les validations auto-validees (candidats a la re-association)."""
        statement = (
            select(PendingValidationModel)
            .where(PendingValidationModel.validation_status == "validated")
            .where(PendingValidationModel.auto_validated == True)  # noqa: E712
        )
        models = self._session.exec(statement).all()
        return [self._to_entity(model) for model in models]

    def save(self, validation: PendingValidation) -> PendingValidation:
        """Sauvegarde une validation (insertion ou mise a jour)."""
        # Obtenir l'ID du VideoFile
        video_file_id = None
        if validation.video_file and validation.video_file.id:
            video_file_id = int(validation.video_file.id)
        elif validation.video_file and validation.video_file.path:
            # Chercher ou creer le VideoFile
            saved_vf = self._video_file_repo.save(validation.video_file)
            video_file_id = int(saved_vf.id) if saved_vf.id else None

        if not video_file_id:
            raise ValueError("PendingValidation doit avoir un VideoFile valide")

        # Verifier si la validation existe deja
        existing = None
        if validation.id:
            existing = self._session.get(PendingValidationModel, int(validation.id))

        if existing:
            # Mise a jour
            existing.video_file_id = video_file_id
            existing.candidates_json = (
                json.dumps(validation.candidates) if validation.candidates else None
            )
            existing.auto_validated = validation.auto_validated
            existing.validation_status = validation.validation_status.value
            existing.selected_candidate_id = validation.selected_candidate_id
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return self._to_entity(existing)
        else:
            # Insertion
            model = self._to_model(validation, video_file_id)
            self._session.add(model)
            self._session.commit()
            self._session.refresh(model)
            return self._to_entity(model)

    def delete(self, validation_id: str) -> bool:
        """Supprime une validation par ID. Retourne True si supprimee."""
        model = self._session.get(PendingValidationModel, int(validation_id))
        if model:
            self._session.delete(model)
            self._session.commit()
            return True
        return False
