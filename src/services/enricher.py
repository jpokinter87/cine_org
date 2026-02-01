"""
Service d'enrichissement des metadonnees via API.

EnricherService orchestre l'enrichissement des fichiers video dont les candidats
sont vides ou manquants. Il utilise les clients TMDB/TVDB pour rechercher des
correspondances et scorer les resultats.

Responsabilites:
- Lister les fichiers necessitant un enrichissement (candidats vides)
- Appeler les APIs avec rate limiting (0.25s entre requetes)
- Scorer les resultats via MatcherService
- Persister les candidats trouves
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

from src.core.entities.video import PendingValidation
from src.core.ports.api_clients import SearchResult


# Pattern pour detecter les series via nom de fichier
SERIES_PATTERN = re.compile(r"[Ss]\d{1,2}[Ee]\d{1,2}", re.IGNORECASE)


@dataclass
class EnrichmentResult:
    """Resultat d'un batch d'enrichissement.

    Attributes:
        enriched: Nombre de fichiers enrichis avec succes
        failed: Nombre de fichiers en echec (erreur API)
        skipped: Nombre de fichiers ignores (deja enrichis)
    """

    enriched: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        """Nombre total de fichiers traites."""
        return self.enriched + self.failed + self.skipped


class EnricherService:
    """
    Service d'enrichissement des metadonnees via API.

    Orchestre la recherche de candidats pour les fichiers video sans match,
    en respectant le rate limiting API et en gerant les erreurs gracieusement.

    Attributes:
        RATE_LIMIT_DELAY: Delai entre requetes API (0.25s = 4 req/s pour TMDB)
        MAX_RETRIES: Nombre maximum de tentatives par fichier

    Example:
        enricher = EnricherService(
            pending_repo=repo,
            video_file_repo=vf_repo,
            matcher=matcher,
            tmdb_client=tmdb,
            tvdb_client=tvdb,
        )

        pending = enricher.list_pending_enrichment()
        result = await enricher.enrich_batch(pending, progress_cb, advance_cb)
        print(f"Enrichis: {result.enriched}, Echecs: {result.failed}")
    """

    RATE_LIMIT_DELAY: float = 0.25  # 4 req/s pour TMDB (40/10s)
    MAX_RETRIES: int = 3

    def __init__(
        self,
        pending_repo: Any,
        video_file_repo: Any,
        matcher: Any,
        tmdb_client: Optional[Any] = None,
        tvdb_client: Optional[Any] = None,
    ) -> None:
        """
        Initialise le service d'enrichissement.

        Args:
            pending_repo: Repository pour les validations en attente
            video_file_repo: Repository pour les fichiers video
            matcher: Service de scoring pour les resultats
            tmdb_client: Client TMDB pour les films (optionnel)
            tvdb_client: Client TVDB pour les series (optionnel)
        """
        self._pending_repo = pending_repo
        self._video_file_repo = video_file_repo
        self._matcher = matcher
        self._tmdb_client = tmdb_client
        self._tvdb_client = tvdb_client

    def list_pending_enrichment(self) -> list[PendingValidation]:
        """
        Liste les fichiers necessitant un enrichissement.

        Un fichier necessite un enrichissement si:
        - Sa liste de candidats est vide ou None
        - Il est en statut PENDING

        Returns:
            Liste des PendingValidation sans candidats
        """
        all_pending = self._pending_repo.list_pending()

        # Filtrer ceux sans candidats
        return [p for p in all_pending if not p.candidates]

    def _detect_is_series(self, pending: PendingValidation) -> bool:
        """
        Detecte si un fichier est une serie.

        Detection basee sur:
        1. entity_metadata.get("import_type") si disponible
        2. Pattern SxxExx dans le nom de fichier

        Args:
            pending: La validation en attente

        Returns:
            True si c'est une serie, False sinon
        """
        if pending.video_file:
            # Verifier entity_metadata si disponible
            if hasattr(pending.video_file, "entity_metadata"):
                metadata = getattr(pending.video_file, "entity_metadata", None)
                if metadata and isinstance(metadata, dict):
                    import_type = metadata.get("import_type")
                    if import_type == "series":
                        return True
                    elif import_type == "movie":
                        return False

            # Fallback: detecter via le nom de fichier
            filename = pending.video_file.filename or ""
            return bool(SERIES_PATTERN.search(filename))

        return False

    def _extract_query_info(
        self, pending: PendingValidation
    ) -> tuple[str, Optional[int], Optional[int]]:
        """
        Extrait les infos de recherche depuis un PendingValidation.

        Utilise guessit pour une extraction fiable du titre et de l'annee.

        Args:
            pending: La validation en attente

        Returns:
            Tuple (query_title, year, duration_seconds)
        """
        from guessit import guessit

        query_title = ""
        year = None
        duration = None

        if pending.video_file:
            filename = pending.video_file.filename or ""
            if filename:
                # Utiliser guessit pour extraire le titre proprement
                try:
                    parsed = guessit(filename)
                    query_title = parsed.get("title", "")
                    year = parsed.get("year")
                except Exception:
                    # Fallback: utiliser le nom sans extension
                    query_title = filename.rsplit(".", 1)[0] if "." in filename else filename

            # Recuperer la duree depuis media_info
            if pending.video_file.media_info:
                duration = pending.video_file.media_info.duration_seconds

        return query_title, year, duration

    async def _enrich_single(self, pending: PendingValidation) -> bool:
        """
        Enrichit un seul fichier avec les APIs.

        Args:
            pending: La validation a enrichir

        Returns:
            True si enrichissement reussi, False sinon

        Raises:
            Exception: En cas d'erreur API non geree
        """
        is_series = self._detect_is_series(pending)
        query_title, year, duration = self._extract_query_info(pending)

        if not query_title:
            logger.warning(
                f"Impossible d'extraire le titre pour {pending.video_file.filename if pending.video_file else 'inconnu'}"
            )
            return False

        # Selectionner le bon client
        client = self._tvdb_client if is_series else self._tmdb_client

        if client is None:
            logger.warning(
                f"Client {'TVDB' if is_series else 'TMDB'} non configure, "
                f"impossible d'enrichir {query_title}"
            )
            return False

        # Verifier que le client a une API key valide
        api_key = getattr(client, "_api_key", None)
        if not api_key:
            logger.warning(
                f"Client {'TVDB' if is_series else 'TMDB'} sans API key, "
                f"impossible d'enrichir {query_title}"
            )
            return False

        # Effectuer la recherche
        logger.debug(f"Recherche {'serie' if is_series else 'film'}: {query_title}")
        results = await client.search(query_title, year=year)

        if not results:
            logger.info(f"Aucun resultat pour: {query_title}")
            return False

        # Scorer les resultats
        scored_results = self._matcher.score_results(
            results=results,
            query_title=query_title,
            query_year=year,
            query_duration=duration,
            is_series=is_series,
        )

        # Convertir en format serialisable (dict)
        candidates = [
            {
                "id": r.id,
                "title": r.title,
                "year": r.year,
                "score": r.score,
                "source": r.source,
            }
            for r in scored_results
        ]

        # Mettre a jour le pending
        pending.candidates = candidates
        self._pending_repo.save(pending)

        logger.info(
            f"Enrichi: {query_title} -> {len(candidates)} candidat(s), "
            f"meilleur score: {candidates[0]['score']:.0f}%"
        )
        return True

    async def enrich_batch(
        self,
        items: list[PendingValidation],
        progress_callback: Optional[Callable[[str], None]] = None,
        advance_callback: Optional[Callable[[], None]] = None,
    ) -> EnrichmentResult:
        """
        Enrichit un batch de fichiers avec rate limiting.

        Args:
            items: Liste des PendingValidation a enrichir
            progress_callback: Callback pour mettre a jour la description (optionnel)
            advance_callback: Callback pour avancer la barre de progression (optionnel)

        Returns:
            EnrichmentResult avec les compteurs de succes/echec
        """
        result = EnrichmentResult()

        for item in items:
            filename = item.video_file.filename if item.video_file else "inconnu"

            # Callback de progression
            if progress_callback:
                progress_callback(filename)

            # Verifier si deja enrichi
            if item.candidates:
                result.skipped += 1
                if advance_callback:
                    advance_callback()
                continue

            # Enrichir avec retry (uniquement sur erreur reseau/API)
            success = False
            retries = 0

            while retries < self.MAX_RETRIES:
                try:
                    success = await self._enrich_single(item)
                    if success:
                        result.enriched += 1
                    else:
                        # Pas de resultat mais pas d'erreur - ne pas retenter
                        result.failed += 1
                    # Sortir de la boucle (succes ou echec sans erreur)
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(
                        f"Erreur enrichissement {filename} (tentative {retries}/{self.MAX_RETRIES}): {e}"
                    )
                    if retries >= self.MAX_RETRIES:
                        logger.error(f"Echec definitif pour {filename}: {e}")
                        result.failed += 1
                    else:
                        # Attendre avant retry (backoff simple)
                        await asyncio.sleep(self.RATE_LIMIT_DELAY * retries)

            # Callback d'avancement
            if advance_callback:
                advance_callback()

            # Rate limiting entre chaque requete
            await asyncio.sleep(self.RATE_LIMIT_DELAY)

        return result
