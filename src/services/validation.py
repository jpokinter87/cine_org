"""
Service de validation orchestrant la logique metier de validation automatique et manuelle.

Le ValidationService centralise les regles de validation (seuil 85%, unicite)
dans un service reutilisable par le CLI et le futur Web.

Responsabilites:
- Auto-validation des fichiers avec score >= 85% et candidat unique
- Selection manuelle d'un candidat parmi les resultats
- Recherche manuelle par titre ou ID externe
- Gestion des statuts (pending, validated, rejected)
"""

from typing import Optional

from src.core.entities.video import PendingValidation, ValidationStatus
from src.core.ports.api_clients import MediaDetails, SearchResult
from src.infrastructure.persistence.repositories.pending_validation_repository import (
    SQLModelPendingValidationRepository,
)
from src.services.matcher import MatcherService


# Seuil d'auto-validation (score minimum en pourcentage)
THRESHOLD = 85


class ValidationService:
    """
    Service de validation pour le workflow de matching.

    Centralise la logique de validation automatique et manuelle des fichiers video.
    Utilise les clients API (TMDB/TVDB) pour la recherche et recuperation des details.

    Example:
        service = ValidationService(
            pending_repo=repo,
            matcher=MatcherService(),
            tmdb_client=tmdb_client,
            tvdb_client=tvdb_client,
        )

        # Auto-validation
        pending = await service.process_auto_validation(pending_item)

        # Validation manuelle
        details = await service.validate_candidate(pending_item, selected_candidate)

        # Recherche manuelle
        results = await service.search_manual("Avatar", year=2009)
    """

    def __init__(
        self,
        pending_repo: SQLModelPendingValidationRepository,
        matcher: MatcherService,
        tmdb_client: Optional[object] = None,
        tvdb_client: Optional[object] = None,
    ) -> None:
        """
        Initialise le service de validation.

        Args:
            pending_repo: Repository pour la persistance des validations
            matcher: Service de scoring pour calculer les correspondances
            tmdb_client: Client TMDB pour les films (optionnel)
            tvdb_client: Client TVDB pour les series (optionnel)
        """
        self._pending_repo = pending_repo
        self._matcher = matcher
        self._tmdb_client = tmdb_client
        self._tvdb_client = tvdb_client

    def should_auto_validate(self, candidates: list[SearchResult]) -> bool:
        """
        Determine si les candidats permettent une auto-validation.

        L'auto-validation est possible si:
        - Il y a exactement 1 candidat
        - Le score de ce candidat est >= 85%

        Args:
            candidates: Liste des candidats avec leur score

        Returns:
            True si auto-validation possible, False sinon
        """
        if len(candidates) != 1:
            return False

        return candidates[0].score >= THRESHOLD

    async def process_auto_validation(
        self, pending: PendingValidation
    ) -> PendingValidation:
        """
        Traite l'auto-validation d'une entite PendingValidation.

        Si les conditions d'auto-validation sont remplies:
        - Met auto_validated=True
        - Met validation_status=VALIDATED
        - Met selected_candidate_id=candidat[0].id

        Args:
            pending: L'entite PendingValidation a traiter

        Returns:
            L'entite mise a jour (ou inchangee si auto-validation impossible)
        """
        # Convertir les candidats en SearchResult si necessaire
        candidates = self._parse_candidates(pending.candidates)

        if not self.should_auto_validate(candidates):
            return pending

        # Auto-validation possible
        pending.auto_validated = True
        pending.validation_status = ValidationStatus.VALIDATED
        pending.selected_candidate_id = candidates[0].id

        # Persister les changements
        return self._pending_repo.save(pending)

    def _parse_candidates(self, candidates: list) -> list[SearchResult]:
        """
        Parse les candidats depuis leur forme stockee en SearchResult.

        Les candidats peuvent etre stockes sous forme de dict (JSON) ou
        deja etre des SearchResult.

        Args:
            candidates: Liste de candidats (dict ou SearchResult)

        Returns:
            Liste de SearchResult
        """
        if not candidates:
            return []

        parsed = []
        for c in candidates:
            if isinstance(c, SearchResult):
                parsed.append(c)
            elif isinstance(c, dict):
                parsed.append(
                    SearchResult(
                        id=c.get("id", ""),
                        title=c.get("title", ""),
                        year=c.get("year"),
                        score=c.get("score", 0.0),
                        source=c.get("source", ""),
                    )
                )
        return parsed

    async def validate_candidate(
        self, pending: PendingValidation, candidate: SearchResult
    ) -> MediaDetails:
        """
        Valide un candidat selectionne et recupere ses details.

        Met a jour le statut de la validation et recupere les details
        complets du media depuis l'API appropriee.

        Args:
            pending: L'entite PendingValidation concernee
            candidate: Le candidat selectionne

        Returns:
            Les MediaDetails du candidat selectionne

        Raises:
            ValueError: Si le client API necessaire n'est pas disponible
            ValueError: Si les details ne peuvent pas etre recuperes
        """
        # Recuperer les details via le bon client
        details = await self._get_details_from_source(candidate.source, candidate.id)

        if details is None:
            raise ValueError(
                f"Impossible de recuperer les details pour {candidate.id} "
                f"depuis {candidate.source}"
            )

        # Mettre a jour le statut
        pending.validation_status = ValidationStatus.VALIDATED
        pending.selected_candidate_id = candidate.id

        # Persister les changements
        self._pending_repo.save(pending)

        return details

    async def _get_details_from_source(
        self, source: str, media_id: str
    ) -> Optional[MediaDetails]:
        """
        Recupere les details d'un media depuis la source appropriee.

        Args:
            source: Identifiant de la source ("tmdb" ou "tvdb")
            media_id: ID du media dans la source

        Returns:
            MediaDetails ou None si non trouve ou client non disponible
        """
        if source == "tmdb":
            if self._tmdb_client is None:
                return None
            # Verifier si le client a une api_key valide
            api_key = getattr(self._tmdb_client, "_api_key", None)
            if not api_key:
                return None
            return await self._tmdb_client.get_details(media_id)

        elif source == "tvdb":
            if self._tvdb_client is None:
                return None
            # Verifier si le client a une api_key valide
            api_key = getattr(self._tvdb_client, "_api_key", None)
            if not api_key:
                return None
            return await self._tvdb_client.get_details(media_id)

        return None

    def reject_pending(self, pending: PendingValidation) -> PendingValidation:
        """
        Rejette une validation en attente.

        Met le statut a REJECTED, ce qui indique que l'utilisateur
        a decide de ne pas valider ce fichier.

        Args:
            pending: L'entite PendingValidation a rejeter

        Returns:
            L'entite mise a jour avec status=REJECTED
        """
        pending.validation_status = ValidationStatus.REJECTED
        return self._pending_repo.save(pending)

    async def search_manual(
        self,
        query: str,
        is_series: bool = False,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Effectue une recherche manuelle par titre.

        Permet a l'utilisateur de rechercher un media par titre
        si les resultats automatiques ne correspondent pas.

        Args:
            query: Titre a rechercher
            is_series: True pour chercher une serie (TVDB), False pour un film (TMDB)
            year: Annee optionnelle pour filtrer les resultats

        Returns:
            Liste des resultats de recherche (vide si client non disponible)
        """
        if is_series:
            if self._tvdb_client is None:
                return []
            # Verifier si le client a une api_key valide
            api_key = getattr(self._tvdb_client, "_api_key", None)
            if not api_key:
                return []
            return await self._tvdb_client.search(query, year=year)
        else:
            if self._tmdb_client is None:
                return []
            # Verifier si le client a une api_key valide
            api_key = getattr(self._tmdb_client, "_api_key", None)
            if not api_key:
                return []
            return await self._tmdb_client.search(query, year=year)

    async def search_by_external_id(
        self, id_type: str, id_value: str
    ) -> Optional[MediaDetails]:
        """
        Recherche un media par son ID externe.

        Permet de rechercher directement par ID TMDB, TVDB ou IMDB.

        Args:
            id_type: Type d'ID ("tmdb", "tvdb", "imdb")
            id_value: Valeur de l'ID

        Returns:
            MediaDetails si trouve, None sinon
        """
        if id_type == "tmdb":
            if self._tmdb_client is None:
                return None
            api_key = getattr(self._tmdb_client, "_api_key", None)
            if not api_key:
                return None
            return await self._tmdb_client.get_details(id_value)

        elif id_type == "tvdb":
            if self._tvdb_client is None:
                return None
            api_key = getattr(self._tvdb_client, "_api_key", None)
            if not api_key:
                return None
            return await self._tvdb_client.get_details(id_value)

        elif id_type == "imdb":
            # TMDB supporte la recherche par IMDB ID via l'endpoint /find
            # Pour simplifier, on utilise get_details avec l'ID IMDB
            # Note: Dans une version complete, on utiliserait /find/{external_id}
            if self._tmdb_client is None:
                return None
            api_key = getattr(self._tmdb_client, "_api_key", None)
            if not api_key:
                return None
            # TMDB get_details attend un ID TMDB, pas IMDB
            # Pour IMDB, il faudrait un endpoint specifique - retourne None pour l'instant
            return None

        return None

    def list_pending(self) -> list[PendingValidation]:
        """
        Liste toutes les validations en statut 'pending'.

        Returns:
            Liste des PendingValidation avec status=PENDING
        """
        return self._pending_repo.list_pending()

    def list_validated(self) -> list[PendingValidation]:
        """
        Liste toutes les validations avec statut 'validated'.

        Returns:
            Liste des PendingValidation avec status=VALIDATED
        """
        # Le repository n'a pas de methode list_validated,
        # on filtre manuellement
        all_pending = self._pending_repo.list_pending()
        # list_pending ne retourne que les PENDING, on doit faire autrement

        # Utiliser une requete directe via le repository
        # Comme le repo n'expose pas cette methode, on utilise une approche alternative
        # En attendant une methode dediee, on peut lister tous et filtrer
        # Note: Idealement, ajouter list_by_status(status) au repository
        return self._list_by_status(ValidationStatus.VALIDATED)

    def _list_by_status(self, status: ValidationStatus) -> list[PendingValidation]:
        """
        Liste les validations par statut.

        Methode interne utilisant le repository avec filtrage Python.
        Note: Pourrait etre optimise avec une methode repository dediee.

        Args:
            status: Statut a filtrer

        Returns:
            Liste des PendingValidation avec le statut demande
        """
        # Acces direct a la session du repository pour une requete custom
        # C'est un compromis acceptable en attendant une methode repository
        from sqlmodel import select

        from src.infrastructure.persistence.models import PendingValidationModel

        statement = select(PendingValidationModel).where(
            PendingValidationModel.validation_status == status.value
        )
        models = self._pending_repo._session.exec(statement).all()
        return [self._pending_repo._to_entity(model) for model in models]
