"""
Service de réalignement des fichiers d'une série sur sa fiche canonique.

Après une ré-association, le SeriesModel porte le bon titre et la bonne année
mais les fichiers restent nommés d'après l'ancienne association (dossier
« Found (2017) », titres d'épisodes du documentaire). Ce service renomme le
dossier de série (storage/ et video/), les fichiers physiques, recrée les
symlinks et met à jour les chemins en base.

Le hardlink de seeding dans downloads/ est préservé : os.rename() sur storage/
conserve l'inode, donc le hardlink reste valide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from src.core.entities.media import Episode, Series
from src.core.ports.parser import IMediaInfoExtractor
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.renamer import generate_series_filename, sanitize_for_filesystem


@dataclass
class EpisodeRenameOutcome:
    """
    Résultat d'une tentative de renommage pour un épisode.

    ``status`` vaut "renamed", "already_canonical", "file_missing",
    "conflict" ou "error".
    """

    episode_id: int
    status: str
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    reason: Optional[str] = None


def _series_folder_name(series: SeriesModel) -> str:
    """Nom canonique du dossier de série : « Titre (Année) »."""
    name = sanitize_for_filesystem(series.title)
    return f"{name} ({series.year})" if series.year else name


def _to_series_entity(model: SeriesModel) -> Series:
    """Construit une entité Series pour le renamer."""
    return Series(
        id=str(model.id) if model.id is not None else None,
        tvdb_id=model.tvdb_id,
        tmdb_id=model.tmdb_id,
        title=model.title,
        original_title=model.original_title,
        year=model.year,
    )


def _to_episode_entity(model: EpisodeModel) -> Episode:
    """Construit une entité Episode pour le renamer."""
    return Episode(
        id=str(model.id) if model.id is not None else None,
        season_number=model.season_number,
        episode_number=model.episode_number,
        episode_end=model.episode_end,
        title=model.title,
        is_extra=model.is_extra,
    )


class SeriesRenamer:
    """Renomme les fichiers d'une série selon le titre canonique de la DB."""

    def __init__(
        self,
        session: Session,
        media_info_extractor: IMediaInfoExtractor,
    ) -> None:
        self._session = session
        self._extractor = media_info_extractor

    def rename_series(
        self, series_id: int, dry_run: bool = True
    ) -> list[EpisodeRenameOutcome]:
        """
        Réaligne les fichiers d'une série sur son titre/année canoniques.

        Args:
            series_id: ID interne de la série.
            dry_run: si vrai (défaut), rien n'est écrit ni sur disque ni en base.

        Returns:
            Un résultat par épisode possédant un fichier ; liste vide si la
            série est inconnue ou n'a aucun fichier sur disque.
        """
        series = self._session.get(SeriesModel, series_id)
        if series is None:
            return []

        episodes = [
            ep
            for ep in self._session.exec(
                select(EpisodeModel)
                .where(EpisodeModel.series_id == series_id)
                .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
            ).all()
            if ep.file_path
        ]
        if not episodes:
            return []

        folder_moves = self._move_series_folders(series, episodes, dry_run)

        return [
            self._rename_episode(series, ep, folder_moves, dry_run) for ep in episodes
        ]

    def _move_series_folders(
        self,
        series: SeriesModel,
        episodes: list[EpisodeModel],
        dry_run: bool,
    ) -> dict[Path, Path]:
        """
        Renomme les dossiers de série (storage/ et video/) et retourne la
        correspondance ancien → nouveau chemin.

        En dry-run la correspondance est calculée sans rien déplacer.
        Un dossier dont la cible existe déjà est laissé en place : les fichiers
        seront simplement renommés à l'intérieur.
        """
        wanted = _series_folder_name(series)
        candidates: set[Path] = set()
        for ep in episodes:
            for raw in (ep.file_path, ep.symlink_path):
                if raw:
                    # .../<Série>/<Saison XX>/<fichier>
                    candidates.add(Path(raw).parent.parent)

        moves: dict[Path, Path] = {}
        for old_dir in candidates:
            if old_dir.name == wanted:
                continue
            new_dir = old_dir.with_name(wanted)
            if new_dir.exists():
                logger.warning(
                    "Dossier de série non renommé, la cible existe déjà : {}", new_dir
                )
                continue
            if not dry_run:
                if not old_dir.is_dir():
                    continue
                try:
                    old_dir.rename(new_dir)
                except OSError as e:
                    logger.error("Renommage du dossier {} impossible : {}", old_dir, e)
                    continue
                logger.info("Dossier série renommé : {} → {}", old_dir.name, wanted)
            moves[old_dir] = new_dir

        return moves

    def _relocate(
        self,
        path: Path,
        moves: dict[Path, Path],
        season_folder: Optional[str] = None,
    ) -> Path:
        """
        Applique les renommages de dossiers à un chemin de fichier.

        ``season_folder`` force le dossier de saison canonique : un épisode
        dont le numéro de saison a été corrigé en base change de dossier.
        """
        series_dir = path.parent.parent
        new_dir = moves.get(series_dir, series_dir)
        return new_dir / (season_folder or path.parent.name) / path.name

    @staticmethod
    def _prune_empty_dir(directory: Path) -> None:
        """Retire un dossier de saison vidé par le déplacement d'un épisode."""
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError as e:
            logger.debug("Dossier {} non supprimé : {}", directory, e)

    def _rename_episode(
        self,
        series: SeriesModel,
        episode: EpisodeModel,
        moves: dict[Path, Path],
        dry_run: bool,
    ) -> EpisodeRenameOutcome:
        """Renomme le fichier storage et recrée le symlink d'un épisode."""
        original = Path(episode.file_path)
        season_folder = f"Saison {episode.season_number:02d}"
        # En dry-run les dossiers n'ont pas bougé : le fichier est encore à
        # son emplacement d'origine, seule la destination finale est calculée.
        current = original if dry_run else self._relocate(original, moves)
        if not current.exists():
            return EpisodeRenameOutcome(
                episode_id=episode.id,
                status="file_missing",
                old_name=original.name,
                reason=str(current),
            )

        media_info = None
        try:
            media_info = self._extractor.extract(current)
        except Exception as e:
            logger.debug("MediaInfo échoue pour {} : {}", current, e)

        new_name = generate_series_filename(
            _to_series_entity(series),
            _to_episode_entity(episode),
            media_info,
            current.suffix,
        )
        final = self._relocate(original, moves, season_folder).with_name(new_name)

        if final == original:
            return EpisodeRenameOutcome(
                episode_id=episode.id,
                status="already_canonical",
                old_name=original.name,
                new_name=new_name,
            )

        if final != current and final.exists():
            return EpisodeRenameOutcome(
                episode_id=episode.id,
                status="conflict",
                old_name=original.name,
                new_name=new_name,
                reason="storage_target_exists",
            )

        if dry_run:
            return EpisodeRenameOutcome(
                episode_id=episode.id,
                status="renamed",
                old_name=original.name,
                new_name=new_name,
            )

        current_symlink = (
            self._relocate(Path(episode.symlink_path), moves)
            if episode.symlink_path
            else None
        )
        final_symlink = (
            self._relocate(Path(episode.symlink_path), moves, season_folder).with_name(
                new_name
            )
            if episode.symlink_path
            else None
        )

        try:
            if final != current:
                final.parent.mkdir(parents=True, exist_ok=True)
                current.rename(final)
            if final_symlink is not None:
                if current_symlink.is_symlink() or current_symlink.exists():
                    current_symlink.unlink()
                final_symlink.parent.mkdir(parents=True, exist_ok=True)
                final_symlink.symlink_to(final)
                episode.symlink_path = str(final_symlink)
            episode.file_path = str(final)
            self._session.add(episode)
            self._session.commit()
            self._prune_empty_dir(current.parent)
            if current_symlink is not None:
                self._prune_empty_dir(current_symlink.parent)
        except OSError as e:
            logger.error("Renommage échoué pour l'épisode {} : {}", episode.id, e)
            return EpisodeRenameOutcome(
                episode_id=episode.id,
                status="error",
                old_name=original.name,
                new_name=new_name,
                reason=str(e),
            )

        return EpisodeRenameOutcome(
            episode_id=episode.id,
            status="renamed",
            old_name=original.name,
            new_name=new_name,
        )
