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

from loguru import logger
from sqlmodel import Session, select

from src.config import Settings
from src.infrastructure.persistence.database import get_engine
from src.infrastructure.persistence.models import HardlinkModel


@dataclass
class PurgeResult:
    """Résultat d'une opération de purge."""

    purged: int = 0
    errors: list[str] = field(default_factory=list)
    freed_paths: list[str] = field(default_factory=list)


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

    def __init__(self, settings: Settings):
        self._settings = settings

    def purge_expired(
        self, force_all: bool = False, dry_run: bool = False
    ) -> PurgeResult:
        """
        Supprime les hardlinks expirés (ou tous si force_all).

        Le fichier dans storage/ reste intact — seul le hardlink dans
        downloads/ est supprimé (décrémente le link count).
        Les dossiers parents vides sont nettoyés.
        """
        result = PurgeResult()
        now = datetime.utcnow()

        with Session(get_engine()) as session:
            if force_all:
                statement = select(HardlinkModel)
            else:
                statement = select(HardlinkModel).where(HardlinkModel.expires_at < now)
            hardlinks = list(session.exec(statement).all())

            if not hardlinks:
                return result

            for hardlink in hardlinks:
                download_path = Path(hardlink.download_path)

                if dry_run:
                    result.freed_paths.append(hardlink.download_path)
                    result.purged += 1
                    continue

                # Supprimer le hardlink dans downloads/
                try:
                    if download_path.exists() and not download_path.is_symlink():
                        os.unlink(download_path)
                        result.freed_paths.append(hardlink.download_path)
                        logger.debug("Hardlink purgé : {}", download_path.name)
                    else:
                        # Fichier déjà absent — nettoyer l'entrée DB
                        result.freed_paths.append(hardlink.download_path)
                except OSError as e:
                    result.errors.append(f"{download_path.name}: {e}")
                    continue

                # Nettoyage des dossiers parents vides
                self._cleanup_empty_parents(download_path)

                # Supprimer l'entrée DB
                session.delete(hardlink)
                result.purged += 1

            if not dry_run:
                session.commit()

        return result

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

    def _cleanup_empty_parents(self, file_path: Path) -> None:
        """Remonte les dossiers parents et supprime les vides jusqu'à downloads_dir."""
        downloads_dir = self._settings.downloads_dir
        current = file_path.parent

        while current != downloads_dir and current.is_relative_to(downloads_dir):
            try:
                current.rmdir()  # Échoue si non vide
                logger.debug("Dossier vide supprimé : {}", current)
                current = current.parent
            except OSError:
                break  # Dossier non vide, on s'arrête
