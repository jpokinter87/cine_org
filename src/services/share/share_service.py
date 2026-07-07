"""Orchestration du partage Jellyfin : préparation, démontage, surveillance."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from src.adapters.api.jellyfin_client import JellyfinClient
from src.adapters.funnel import FunnelController
from src.infrastructure.persistence.models import (
    MovieModel,
    SeriesModel,
    ShareSessionModel,
)
from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)
from src.services.share.builder import JellyfinShareBuilder
from src.services.share.exceptions import ShareConflict, ShareError

LIB_FILMS = "Partage Films"
LIB_SERIES = "Partage Séries"


class ShareService:
    """Orchestre le partage éphémère : démarrage, arrêt, surveillance idle/plafond."""

    def __init__(
        self,
        *,
        session: Session,
        partage_dir: Path | str,
        jellyfin_client: JellyfinClient,
        funnel: FunnelController,
        idle_timeout: timedelta = timedelta(minutes=30),
        hard_cap: timedelta = timedelta(hours=6),
    ) -> None:
        self._session = session
        self._partage_dir = Path(partage_dir)
        self._jellyfin = jellyfin_client
        self._funnel = funnel
        self._idle_timeout = idle_timeout
        self._hard_cap = hard_cap
        self._repo = ShareSessionRepository(session)
        self._builder = JellyfinShareBuilder(session, partage_dir)

    def get_active_share(self) -> ShareSessionModel | None:
        """Retourne le partage actif, ou None si aucun."""
        return self._repo.get_active()

    async def start_share(
        self, media_type: str, media_id: int, replace: bool = False
    ) -> ShareSessionModel:
        """Démarre un partage pour le média indiqué.

        Si un partage est déjà actif :
        - sans replace → lève ShareConflict
        - avec replace → démonte l'existant avant de démarrer

        Ordre des opérations : populate → refresh Jellyfin → enable Funnel → persist.
        """
        active = self._repo.get_active()
        if active is not None:
            if not replace:
                raise ShareConflict(active)
            await self._teardown(active)

        self._builder.clear()
        if media_type == "movie":
            movie = self._session.get(MovieModel, media_id)
            if movie is None:
                raise ShareError(f"Film introuvable : {media_id}")
            title = movie.title
            folder = self._builder.populate_movie(media_id)
            await self._jellyfin.refresh_library(LIB_FILMS)
        elif media_type == "series":
            series = self._session.get(SeriesModel, media_id)
            if series is None:
                raise ShareError(f"Série introuvable : {media_id}")
            title = series.title
            folder = self._builder.populate_series(media_id)
            await self._jellyfin.refresh_library(LIB_SERIES)
        else:
            raise ShareError(f"Type de média inconnu : {media_type}")

        if not self._funnel.enable():
            self._builder.clear()
            raise ShareError("Le Funnel n'a pas pu être activé")

        return self._repo.start(
            media_type=media_type, media_id=media_id, title=title, folder_name=folder
        )

    async def stop_share(self) -> None:
        """Arrête le partage actif. Si aucun partage actif, désactive quand même
        le Funnel par auto-réparation (état incohérent)."""
        active = self._repo.get_active()
        if active is None:
            self._funnel.disable()
            return
        await self._teardown(active)

    async def _teardown(self, active: ShareSessionModel) -> None:
        """Désactive le Funnel, vide le dossier Partage, rafraîchit Jellyfin, désactive en DB."""
        self._funnel.disable()
        self._builder.clear()
        await self._jellyfin.refresh_library(LIB_FILMS)
        await self._jellyfin.refresh_library(LIB_SERIES)
        self._repo.deactivate(active)

    async def run_monitor_tick(self, now: datetime) -> str | None:
        """Surveillance périodique appelée par le planificateur.

        Logique :
        1. Aucun partage actif → rien à faire (None).
        2. Plafond dur dépassé → démontage, retourne "hard_cap".
        3. Lecture en cours → touche last_played_at, retourne None.
        4. Idle trop long (dernière lecture ou démarrage + timeout) → démontage, "idle".
        """
        active = self._repo.get_active()
        if active is None:
            return None

        if now - active.started_at >= self._hard_cap:
            await self._teardown(active)
            return "hard_cap"

        sessions = await self._jellyfin.get_active_sessions()
        if self._is_shared_playing(sessions):
            self._repo.touch_played(active, now)
            return None

        last = active.last_played_at or active.started_at
        if now - last >= self._idle_timeout:
            await self._teardown(active)
            return "idle"

        return None

    async def reconcile_on_startup(self) -> None:
        """Réconciliation au démarrage : si le Funnel est allumé sans partage actif,
        on le coupe pour éviter un tunnel ouvert orphelin."""
        if self._repo.get_active() is None and self._funnel.is_on():
            self._funnel.disable()

    def _is_shared_playing(self, sessions: list[dict]) -> bool:
        """Retourne True si au moins une session lit un fichier sous partage_dir."""
        root = str(self._partage_dir)
        for sess in sessions:
            item = sess.get("NowPlayingItem") or {}
            path = item.get("Path") or ""
            if path.startswith(root):
                return True
        return False
