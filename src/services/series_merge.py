"""Service de fusion de deux fiches séries dupliquées en une seule.

Réunifie la série via les symlinks `video/` (jamais le storage physique),
conformément aux invariants d'ingestion du projet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.core.entities.media import Episode, Series
from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.infrastructure.persistence.models import EpisodeModel


@dataclass
class EpisodeConflict:
    """Épisode présent dans les deux fiches (même saison/numéro)."""

    season_number: int
    episode_number: int
    recipient_episode_id: int
    absorbed_episode_id: int
    kept: str  # "recipient" | "absorbed"


@dataclass
class MergePreview:
    """Aperçu calculé d'une fusion, sans aucune mutation."""

    recipient_id: int
    absorbed_id: int
    recipient_title: str
    absorbed_title: str
    episodes_to_attach: int
    conflicts: list[EpisodeConflict] = field(default_factory=list)
    metadata_completed: dict[str, object] = field(default_factory=dict)
    target_series_folder: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """Résultat d'une fusion effectuée."""

    recipient_id: int
    episodes_attached: int
    conflicts_resolved: int
    symlinks_regenerated: int
    absorbed_archived: bool


def build_media_info_from_episode(model: EpisodeModel) -> MediaInfo:
    """Reconstruit un MediaInfo depuis les colonnes techniques d'un EpisodeModel.

    Réplique le pattern de `video_file_repository._to_entity`. La résolution est
    stockée à plat (« 1920x1080 ») et reparsée en Resolution(width, height).
    """
    resolution = None
    if model.resolution and "x" in model.resolution:
        parts = model.resolution.split("x")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            resolution = Resolution(width=int(parts[0]), height=int(parts[1]))

    video_codec = VideoCodec(name=model.codec_video) if model.codec_video else None

    audio_codecs: tuple[AudioCodec, ...] = ()
    if model.codec_audio:
        audio_codecs = (AudioCodec(name=model.codec_audio),)

    audio_languages: tuple[Language, ...] = ()
    if model.languages_json:
        codes = json.loads(model.languages_json)
        audio_languages = tuple(Language(code=code, name=code) for code in codes)

    return MediaInfo(
        resolution=resolution,
        video_codec=video_codec,
        audio_codecs=audio_codecs,
        audio_languages=audio_languages,
        duration_seconds=model.duration_seconds,
    )


class SeriesMergeService:
    """Fusionne deux fiches séries en une seule (symlinks uniquement)."""

    def __init__(
        self,
        session,
        video_dir: Path,
        file_system,
        organizer,
        renamer,
        duplicate_detector,
        series_repo,
        episode_repo,
    ) -> None:
        self._session = session
        self._video_dir = Path(video_dir)
        self._fs = file_system
        self._organizer = organizer
        self._renamer = renamer
        self._dup = duplicate_detector
        self._series_repo = series_repo
        self._episode_repo = episode_repo

    # Champs de métadonnées complétables (on ne touche jamais au titre du récipiendaire)
    _FILLABLE_FIELDS = (
        "tvdb_id", "tmdb_id", "imdb_id", "year", "overview", "poster_path",
        "director", "genres_json", "cast_json", "vote_average", "vote_count",
        "imdb_rating", "imdb_votes",
    )

    def _load_models(self, recipient_id, absorbed_id):
        """Charge les deux modèles SeriesModel depuis la DB et valide la requête."""
        from src.infrastructure.persistence.models import SeriesModel

        recipient = self._session.get(SeriesModel, recipient_id)
        absorbed = self._session.get(SeriesModel, absorbed_id)
        if recipient is None or absorbed is None:
            raise ValueError("Fiche série introuvable.")
        if recipient_id == absorbed_id:
            raise ValueError("Impossible de fusionner une fiche avec elle-même.")
        return recipient, absorbed

    def _episodes_of(self, series_id):
        """Retourne tous les EpisodeModel d'une série."""
        from sqlmodel import select
        from src.infrastructure.persistence.models import EpisodeModel

        return list(
            self._session.exec(
                select(EpisodeModel).where(EpisodeModel.series_id == series_id)
            ).all()
        )

    def _compute_metadata_completion(self, recipient, absorbed):
        """Retourne les champs que l'absorbée apporte et le récipiendaire n'a pas."""
        completed = {}
        for fieldname in self._FILLABLE_FIELDS:
            current = getattr(recipient, fieldname)
            incoming = getattr(absorbed, fieldname)
            if (current is None or current == "") and incoming not in (None, ""):
                completed[fieldname] = incoming
        return completed

    def _compute_warnings(self, recipient, absorbed):
        """Retourne les avertissements sur des incohérences entre les deux fiches."""
        warnings = []
        if recipient.tmdb_id and absorbed.tmdb_id and recipient.tmdb_id != absorbed.tmdb_id:
            warnings.append(
                "Les deux fiches ont des tmdb_id différents — vérifiez qu'il "
                "s'agit bien de la même série."
            )
        if recipient.year and absorbed.year and recipient.year != absorbed.year:
            warnings.append("Les deux fiches ont des années différentes.")
        return warnings

    def _detect_conflicts(self, recipient_eps, absorbed_eps):
        """Détecte les épisodes présents dans les deux fiches (même saison/numéro)."""
        by_key = {(e.season_number, e.episode_number): e for e in recipient_eps}
        conflicts = []
        for ep in absorbed_eps:
            match = by_key.get((ep.season_number, ep.episode_number))
            if match is not None:
                conflicts.append(
                    EpisodeConflict(
                        season_number=ep.season_number,
                        episode_number=ep.episode_number,
                        recipient_episode_id=match.id,
                        absorbed_episode_id=ep.id,
                        kept=self._pick_better(match, ep),
                    )
                )
        return conflicts

    def _pick_better(self, recipient_ep, absorbed_ep):
        """Choisit l'épisode de meilleure qualité entre le récipiendaire et l'absorbé."""
        from src.services.transferer import ExistingFileInfo

        def info(model):
            return ExistingFileInfo(
                path=Path(model.file_path or ""),
                size_bytes=model.file_size_bytes or 0,
                resolution=model.resolution,
                video_codec=model.codec_video,
                audio_codec=model.codec_audio,
                duration_seconds=model.duration_seconds,
            )

        comparison = self._dup.compare_quality(
            existing_files=[info(recipient_ep)], new_file=info(absorbed_ep)
        )
        return "absorbed" if comparison.recommended == "new" else "recipient"

    def _serialize_series(self, model) -> str:
        """Sérialise un SeriesModel en JSON (pour archivage corbeille)."""
        data = {c.name: getattr(model, c.name) for c in model.__table__.columns}
        return json.dumps(data, default=str, ensure_ascii=False)

    def _archive_series(self, absorbed) -> None:
        """Archive la fiche absorbée dans la corbeille avant suppression."""
        from src.infrastructure.persistence.models import TrashModel

        self._session.add(
            TrashModel(
                entity_type="series",
                original_id=absorbed.id,
                metadata_json=self._serialize_series(absorbed),
                deletion_reason="merge",
            )
        )

    def _apply_metadata_completion(self, recipient, completed) -> None:
        """Applique sur le récipiendaire les champs complétés depuis l'absorbée."""
        from datetime import datetime

        for fieldname, value in completed.items():
            setattr(recipient, fieldname, value)
        recipient.updated_at = datetime.utcnow()

    def _regenerate_for_episode(self, recipient_entity, ep_model) -> int:
        """Régénère le symlink d'un épisode ; retourne 1 si créé, 0 sinon."""
        from datetime import datetime

        if not ep_model.file_path:
            return 0
        storage_path = Path(ep_model.file_path)
        if not storage_path.exists():
            return 0
        if ep_model.symlink_path:
            self._fs.remove_symlink(Path(ep_model.symlink_path))
        ep_entity = self._episode_repo._to_entity(ep_model)
        media_info = build_media_info_from_episode(ep_model)
        new_link = self.regenerate_symlink(
            recipient_entity, ep_entity, media_info, storage_path
        )
        ep_model.symlink_path = str(new_link)
        ep_model.updated_at = datetime.utcnow()
        return 1

    def _resolve_conflicts(self, conflicts, recipient_eps, absorbed_eps) -> int:
        """Résolution des conflits — complétée en Task 5 (stub minimal)."""
        return 0

    def merge(self, recipient_id, absorbed_id) -> MergeResult:
        """Fusionne la fiche absorbée dans la fiche récipiendaire.

        Rattache les épisodes, complète les métadonnées, régénère les symlinks
        sous le dossier canonique, archive puis supprime la fiche absorbée.
        Le storage physique n'est jamais modifié.
        """
        recipient, absorbed = self._load_models(recipient_id, absorbed_id)
        self._merge_recipient_id = recipient_id
        recipient_eps = self._episodes_of(recipient_id)
        absorbed_eps = self._episodes_of(absorbed_id)
        conflicts = self._detect_conflicts(recipient_eps, absorbed_eps)
        conflict_by_key = {(c.season_number, c.episode_number): c for c in conflicts}

        # 1. Compléter les métadonnées de R
        self._apply_metadata_completion(
            recipient, self._compute_metadata_completion(recipient, absorbed)
        )

        # 2. Résoudre les conflits (complété en Task 5)
        resolved = self._resolve_conflicts(conflicts, recipient_eps, absorbed_eps)

        # 3. Rattacher les épisodes de A sans conflit
        attached = 0
        for ep in absorbed_eps:
            if (ep.season_number, ep.episode_number) in conflict_by_key:
                continue
            ep.series_id = recipient_id
            attached += 1

        # 4. Régénérer les symlinks de TOUS les épisodes désormais sous R
        self._session.flush()
        recipient_entity = self._series_repo._to_entity(recipient)
        regenerated = 0
        for ep in self._episodes_of(recipient_id):
            regenerated += self._regenerate_for_episode(recipient_entity, ep)

        # 5. Archiver puis supprimer la fiche A
        self._archive_series(absorbed)
        self._session.delete(absorbed)
        self._session.commit()

        return MergeResult(
            recipient_id=recipient_id,
            episodes_attached=attached,
            conflicts_resolved=resolved,
            symlinks_regenerated=regenerated,
            absorbed_archived=True,
        )

    def preview(self, recipient_id, absorbed_id) -> MergePreview:
        """Calcule un aperçu de la fusion sans effectuer aucune mutation.

        Args:
            recipient_id: ID de la fiche qui conserve les épisodes.
            absorbed_id: ID de la fiche à absorber.

        Retourne:
            MergePreview décrivant ce que la fusion ferait.
        """
        recipient, absorbed = self._load_models(recipient_id, absorbed_id)
        recipient_eps = self._episodes_of(recipient_id)
        absorbed_eps = self._episodes_of(absorbed_id)
        conflicts = self._detect_conflicts(recipient_eps, absorbed_eps)
        conflict_keys = {(c.season_number, c.episode_number) for c in conflicts}
        to_attach = sum(
            1 for e in absorbed_eps
            if (e.season_number, e.episode_number) not in conflict_keys
        )
        recipient_entity = self._series_repo._to_entity(recipient)
        folder = (
            f"{recipient_entity.title} ({recipient_entity.year})"
            if recipient_entity.year else recipient_entity.title
        )
        return MergePreview(
            recipient_id=recipient_id,
            absorbed_id=absorbed_id,
            recipient_title=recipient.title,
            absorbed_title=absorbed.title,
            episodes_to_attach=to_attach,
            conflicts=conflicts,
            metadata_completed=self._compute_metadata_completion(recipient, absorbed),
            target_series_folder=folder,
            warnings=self._compute_warnings(recipient, absorbed),
        )

    def regenerate_symlink(
        self,
        series: Series,
        episode: Episode,
        media_info: MediaInfo,
        storage_path: Path,
    ) -> Path:
        """(Re)crée le symlink d'un épisode sous le dossier canonique de `series`.

        Le fichier physique `storage_path` n'est jamais déplacé.
        """
        dest_dir = self._organizer.get_series_video_destination(
            series, episode.season_number, self._video_dir
        )
        extension = storage_path.suffix
        filename = self._renamer.generate_series_filename(
            series=series, episode=episode, media_info=media_info, extension=extension
        )
        new_link = dest_dir / filename
        self._fs.create_symlink(storage_path, new_link)
        return new_link
