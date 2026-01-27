"""
Implementation SQLModel du repository VideoFile.

Implemente l'interface IVideoFileRepository pour la persistance des fichiers video
dans la base de donnees SQLite via SQLModel.
"""

import json
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.repositories import IVideoFileRepository
from src.core.value_objects import MediaInfo, Resolution, VideoCodec, AudioCodec, Language
from src.infrastructure.persistence.models import PendingValidationModel, VideoFileModel


class SQLModelVideoFileRepository(IVideoFileRepository):
    """
    Repository SQLModel pour les fichiers video.

    Implemente IVideoFileRepository avec conversion bidirectionnelle
    entre l'entite VideoFile (domaine) et VideoFileModel (persistance).
    """

    def __init__(self, session: Session) -> None:
        """
        Initialise le repository avec une session SQLModel.

        Args :
            session : Session SQLModel active pour les operations DB
        """
        self._session = session

    def _to_entity(self, model: VideoFileModel) -> VideoFile:
        """
        Convertit un modele DB en entite domaine.

        Args :
            model : Le modele VideoFileModel depuis la DB

        Retourne :
            L'entite VideoFile correspondante
        """
        # Reconstruire MediaInfo depuis les champs plats
        media_info = None
        if (
            model.resolution_width
            or model.resolution_height
            or model.codec_video
            or model.codec_audio
            or model.duration_seconds
        ):
            resolution = None
            if model.resolution_width and model.resolution_height:
                resolution = Resolution(
                    width=model.resolution_width, height=model.resolution_height
                )

            video_codec = None
            if model.codec_video:
                video_codec = VideoCodec(name=model.codec_video)

            audio_codecs = ()
            if model.codec_audio:
                audio_codecs = (AudioCodec(name=model.codec_audio),)

            # Deserialiser les langues depuis JSON
            audio_languages = ()
            if model.languages_json:
                lang_codes = json.loads(model.languages_json)
                audio_languages = tuple(
                    Language(code=code, name=code) for code in lang_codes
                )

            media_info = MediaInfo(
                resolution=resolution,
                video_codec=video_codec,
                audio_codecs=audio_codecs,
                audio_languages=audio_languages,
                duration_seconds=model.duration_seconds,
            )

        return VideoFile(
            id=str(model.id) if model.id else None,
            path=Path(model.path) if model.path else None,
            filename=model.filename,
            size_bytes=model.size_bytes,
            file_hash=model.file_hash,
            media_info=media_info,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: VideoFile) -> VideoFileModel:
        """
        Convertit une entite domaine en modele DB.

        Args :
            entity : L'entite VideoFile du domaine

        Retourne :
            Le modele VideoFileModel pour la persistance
        """
        model = VideoFileModel(
            path=str(entity.path) if entity.path else "",
            filename=entity.filename,
            size_bytes=entity.size_bytes,
            file_hash=entity.file_hash,
        )

        # Decomposer MediaInfo en champs plats
        if entity.media_info:
            mi = entity.media_info
            if mi.resolution:
                model.resolution_width = mi.resolution.width
                model.resolution_height = mi.resolution.height
            if mi.video_codec:
                model.codec_video = mi.video_codec.name
            if mi.audio_codecs:
                model.codec_audio = mi.audio_codecs[0].name
            if mi.audio_languages:
                model.languages_json = json.dumps(
                    [lang.code for lang in mi.audio_languages]
                )
            if mi.duration_seconds:
                model.duration_seconds = mi.duration_seconds

        if entity.id:
            model.id = int(entity.id)

        return model

    def get_by_id(self, video_id: str) -> Optional[VideoFile]:
        """Recupere un fichier video par son ID."""
        statement = select(VideoFileModel).where(VideoFileModel.id == int(video_id))
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_path(self, path: Path) -> Optional[VideoFile]:
        """Recupere un fichier video par son chemin."""
        statement = select(VideoFileModel).where(VideoFileModel.path == str(path))
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def get_by_hash(self, file_hash: str) -> Optional[VideoFile]:
        """Recupere un fichier video par son hash de contenu."""
        statement = select(VideoFileModel).where(VideoFileModel.file_hash == file_hash)
        model = self._session.exec(statement).first()
        if model:
            return self._to_entity(model)
        return None

    def save(self, video_file: VideoFile) -> VideoFile:
        """Sauvegarde un fichier video (insertion ou mise a jour)."""
        # Verifier si le fichier existe deja par ID ou path
        existing = None
        if video_file.id:
            existing = self._session.get(VideoFileModel, int(video_file.id))
        elif video_file.path:
            statement = select(VideoFileModel).where(
                VideoFileModel.path == str(video_file.path)
            )
            existing = self._session.exec(statement).first()

        if existing:
            # Mise a jour
            existing.filename = video_file.filename
            existing.size_bytes = video_file.size_bytes
            existing.file_hash = video_file.file_hash
            if video_file.media_info:
                mi = video_file.media_info
                if mi.resolution:
                    existing.resolution_width = mi.resolution.width
                    existing.resolution_height = mi.resolution.height
                if mi.video_codec:
                    existing.codec_video = mi.video_codec.name
                if mi.audio_codecs:
                    existing.codec_audio = mi.audio_codecs[0].name
                if mi.audio_languages:
                    existing.languages_json = json.dumps(
                        [lang.code for lang in mi.audio_languages]
                    )
                if mi.duration_seconds:
                    existing.duration_seconds = mi.duration_seconds
            self._session.add(existing)
            self._session.commit()
            self._session.refresh(existing)
            return self._to_entity(existing)
        else:
            # Insertion
            model = self._to_model(video_file)
            self._session.add(model)
            self._session.commit()
            self._session.refresh(model)
            return self._to_entity(model)

    def delete(self, video_id: str) -> bool:
        """Supprime un fichier video par ID. Retourne True si supprime."""
        model = self._session.get(VideoFileModel, int(video_id))
        if model:
            self._session.delete(model)
            self._session.commit()
            return True
        return False

    def list_pending(self) -> list[PendingValidation]:
        """Liste tous les fichiers video avec une validation en attente."""
        statement = select(PendingValidationModel).where(
            PendingValidationModel.validation_status == "pending"
        )
        models = self._session.exec(statement).all()
        result = []
        for pv_model in models:
            # Recuperer le VideoFile associe
            vf_model = self._session.get(VideoFileModel, pv_model.video_file_id)
            if vf_model:
                video_file = self._to_entity(vf_model)
                candidates = (
                    json.loads(pv_model.candidates_json)
                    if pv_model.candidates_json
                    else []
                )
                result.append(
                    PendingValidation(
                        id=str(pv_model.id) if pv_model.id else None,
                        video_file=video_file,
                        candidates=candidates,
                        auto_validated=pv_model.auto_validated,
                        validation_status=ValidationStatus(pv_model.validation_status),
                        selected_candidate_id=pv_model.selected_candidate_id,
                        created_at=pv_model.created_at,
                    )
                )
        return result
