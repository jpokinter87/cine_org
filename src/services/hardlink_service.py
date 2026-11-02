"""
Service de gestion des hardlinks de seeding BitTorrent.

Gère la rotation des hardlinks créés dans downloads/ après transfert :
purge des hardlinks expirés, nettoyage des dossiers vides,
statistiques et listing.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from src.config import Settings
from src.core.ports.torrent_client import (
    ITorrentClient,
    TorrentClientUnavailable,
    TorrentInfo,
)
from src.infrastructure.persistence.database import get_engine
from src.infrastructure.persistence.models import HardlinkModel


def _norm(path) -> str:
    """Chemin normalisé pour comparer les chemins Deluge et ceux de la base."""
    return os.path.normpath(str(path))


@dataclass
class PurgeResult:
    """Résultat d'une opération de purge."""

    purged: int = 0
    errors: list[str] = field(default_factory=list)
    freed_paths: list[str] = field(default_factory=list)
    residuals_removed: int = 0
    # Purge pilotée par le client BitTorrent
    removed_torrents: list[str] = field(default_factory=list)
    deferred: list[tuple[str, int]] = field(default_factory=list)  # (torrent, actifs)
    blocked: list[tuple[str, str]] = field(default_factory=list)  # (torrent, raison)


@dataclass
class HardlinkInfo:
    """Information sur un hardlink actif."""

    download_path: str
    storage_path: str
    created_at: datetime
    expires_at: datetime
    days_remaining: int
    file_exists: bool


@dataclass
class HardlinkStats:
    """Statistiques des hardlinks."""

    total_active: int = 0
    total_expired: int = 0
    total_entries: int = 0


class HardlinkService:
    """Service de gestion et rotation des hardlinks de seeding."""

    def __init__(
        self, settings: Settings, torrent_client: Optional[ITorrentClient] = None
    ):
        self._settings = settings
        self._torrent_client = torrent_client

    def purge_expired(
        self, force_all: bool = False, dry_run: bool = False
    ) -> PurgeResult:
        """
        Purge les hardlinks expirés (ou tous si force_all).

        Le fichier dans storage/ reste intact. Avec un client BitTorrent, le
        torrent est retiré avec ses données quand tous ses fichiers suivis ont
        expiré (reporté sinon, bloqué s'il contient une copie unique) ; un
        client injoignable annule la purge. Sans client, ou pour une entrée
        dont le torrent n'est plus chargé, seul le hardlink downloads/ est
        supprimé et les dossiers parents vides sont nettoyés.
        """
        result = PurgeResult()
        now = datetime.utcnow()

        with Session(get_engine()) as session:
            all_hardlinks = list(session.exec(select(HardlinkModel)).all())
            expired = [h for h in all_hardlinks if force_all or h.expires_at < now]
            if not expired:
                return result

            if self._torrent_client is None:
                for hardlink in expired:
                    self._unlink_entry(session, hardlink, result, dry_run)
            else:
                try:
                    torrents = self._torrent_client.list_torrents()
                except TorrentClientUnavailable as e:
                    result.errors.append(str(e))
                    return result
                self._purge_with_client(
                    session, all_hardlinks, expired, torrents, result, dry_run
                )

            if not dry_run:
                session.commit()

        return result

    def _purge_with_client(
        self,
        session: Session,
        all_hardlinks: list[HardlinkModel],
        expired: list[HardlinkModel],
        torrents: list[TorrentInfo],
        result: PurgeResult,
        dry_run: bool,
    ) -> None:
        """Retire, reporte ou bloque chaque torrent concerné par une entrée expirée."""
        by_file = {_norm(f): t for t in torrents for f in t.files}
        tracked = {_norm(h.download_path): h for h in all_hardlinks}
        expired_ids = {h.id for h in expired}

        handled: set[str] = set()
        for hardlink in expired:
            torrent = by_file.get(_norm(hardlink.download_path))
            if torrent is None:
                self._unlink_entry(session, hardlink, result, dry_run)
                continue
            if torrent.id in handled:
                continue
            handled.add(torrent.id)

            entries = [tracked[_norm(f)] for f in torrent.files if _norm(f) in tracked]
            active = [h for h in entries if h.id not in expired_ids]
            if active:
                result.deferred.append((torrent.name, len(active)))
                continue

            blockers = self._single_copies(torrent)
            if blockers:
                reason = "copie unique : " + ", ".join(blockers)
                result.blocked.append((torrent.name, reason))
                logger.warning("Torrent non retiré {} ({})", torrent.name, reason)
                continue

            if not dry_run:
                try:
                    self._torrent_client.remove(torrent.id)
                except TorrentClientUnavailable as e:
                    result.errors.append(f"{torrent.name}: {e}")
                    continue
                for h in entries:
                    session.delete(h)
                logger.info("Torrent retiré avec ses données : {}", torrent.name)

            result.removed_torrents.append(torrent.name)
            result.freed_paths.extend(h.download_path for h in entries)
            result.purged += len(entries)

    @staticmethod
    def _single_copies(torrent: TorrentInfo) -> list[str]:
        """
        Vidéos du torrent présentes sur disque sans aucun autre lien (nlink < 2).

        Le nombre de liens fait foi plutôt que `storage_path` : une
        ré-association renomme le fichier storage sans mettre l'entrée à jour.
        """
        from src.utils.constants import VIDEO_EXTENSIONS

        return [
            path.name
            for path in torrent.files
            if path.suffix.lower() in VIDEO_EXTENSIONS
            and path.exists()
            and path.stat().st_nlink < 2
        ]

    def _unlink_entry(
        self,
        session: Session,
        hardlink: HardlinkModel,
        result: PurgeResult,
        dry_run: bool,
    ) -> None:
        """Supprime le hardlink downloads/ d'une entrée, ses résidus et l'entrée DB."""
        download_path = Path(hardlink.download_path)

        if dry_run:
            result.freed_paths.append(hardlink.download_path)
            result.purged += 1
            return

        # Supprimer le hardlink dans downloads/
        try:
            if download_path.exists() and not download_path.is_symlink():
                os.unlink(download_path)
                logger.debug("Hardlink purgé : {}", download_path.name)
            # Fichier déjà absent : seule l'entrée DB est nettoyée
            result.freed_paths.append(hardlink.download_path)
        except OSError as e:
            result.errors.append(f"{download_path.name}: {e}")
            return

        # Nettoyage des résidus non-vidéo puis des dossiers parents vides
        result.residuals_removed += self._cleanup_empty_parents(download_path)

        session.delete(hardlink)
        result.purged += 1

    def list_active(self) -> list[HardlinkInfo]:
        """Liste les hardlinks non expirés."""
        now = datetime.utcnow()
        with Session(get_engine()) as session:
            statement = select(HardlinkModel).where(HardlinkModel.expires_at >= now)
            hardlinks = session.exec(statement).all()

            return [
                HardlinkInfo(
                    download_path=h.download_path,
                    storage_path=h.storage_path,
                    created_at=h.created_at,
                    expires_at=h.expires_at,
                    days_remaining=(h.expires_at - now).days,
                    file_exists=Path(h.download_path).exists(),
                )
                for h in hardlinks
            ]

    def get_stats(self) -> HardlinkStats:
        """Statistiques des hardlinks en DB."""
        now = datetime.utcnow()
        with Session(get_engine()) as session:
            all_hardlinks = list(session.exec(select(HardlinkModel)).all())
            active = sum(1 for h in all_hardlinks if h.expires_at >= now)
            expired = sum(1 for h in all_hardlinks if h.expires_at < now)

            return HardlinkStats(
                total_active=active,
                total_expired=expired,
                total_entries=len(all_hardlinks),
            )

    def _cleanup_empty_parents(self, file_path: Path) -> int:
        """
        Nettoie le dossier du hardlink purgé puis supprime les parents vides.

        Avant de remonter, retire les fichiers résiduels non-vidéo (ex. `.nfo`)
        qui empêchent la suppression du dossier — mais uniquement si plus aucun
        fichier vidéo ne subsiste dans l'arborescence (sinon le téléchargement
        est encore actif et on n'y touche pas).

        Retourne le nombre de fichiers résiduels supprimés.
        """
        downloads_dir = self._settings.downloads_dir
        removed = self._remove_residual_files(file_path.parent)

        current = file_path.parent
        while current != downloads_dir and current.is_relative_to(downloads_dir):
            try:
                current.rmdir()  # Échoue si non vide
                logger.debug("Dossier vide supprimé : {}", current)
                current = current.parent
            except OSError:
                break  # Dossier non vide, on s'arrête

        return removed

    def _remove_residual_files(self, directory: Path) -> int:
        """
        Supprime les fichiers non-vidéo d'un dossier de téléchargement résiduel.

        Ne fait rien si le dossier est hors de downloads/, s'il s'agit de la
        racine downloads/, ou s'il contient encore un fichier vidéo (le
        téléchargement reste alors actif). Retourne le nombre de fichiers
        supprimés.
        """
        downloads_dir = self._settings.downloads_dir
        if (
            not directory.is_dir()
            or directory == downloads_dir
            or not directory.is_relative_to(downloads_dir)
        ):
            return 0

        if self._contains_video(directory):
            return 0

        removed = 0
        # Parcours profondeur d'abord : fichiers puis sous-dossiers vidés
        for entry in sorted(
            directory.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            try:
                if entry.is_dir():
                    entry.rmdir()
                else:
                    entry.unlink()
                    removed += 1
                    logger.debug("Résidu non-vidéo supprimé : {}", entry.name)
            except OSError as e:
                logger.warning("Résidu non supprimé {} : {}", entry.name, e)

        return removed

    @staticmethod
    def _contains_video(directory: Path) -> bool:
        """Vrai si l'arborescence contient au moins un fichier vidéo."""
        from src.utils.constants import VIDEO_EXTENSIONS

        return any(
            entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS
            for entry in directory.rglob("*")
        )
