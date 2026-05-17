"""
Dataclasses et enums pour le service de migration NAS.

Definit les structures de donnees echangees entre le scanner, le resolveur
de notes, le planificateur de destination, le constructeur de plan et
l'executeur de transfert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.value_objects.media_info import MediaInfo


class Bucket(str, Enum):
    """Categorie d'aiguillage d'un candidat de migration."""

    MIGRATE = "migrate"  # Note >= seuil : a transferer
    LOW_RATED = "low_rated"  # Note < seuil : non transfere
    UNRATED = "unrated"  # Aucune note disponible : a valider manuellement
    BROKEN = "broken"  # Symlink brise meme apres recherche alternative
    ALREADY_ON_DESTINATION = "already_on_destination"  # Cible deja sur le nouveau NAS
    NON_VIDEO = "non_video"  # Extension non reconnue
    NOT_SYMLINK = "not_symlink"  # Entree presente mais ce n'est pas un symlink
    NEEDS_VALIDATION = "needs_validation"  # Mode raw : match TMDB/TVDB ambigu ou absent
    ALREADY_IN_LIBRARY = "already_in_library"  # Mode raw : oeuvre deja en DB CineOrg avec file_path


class TransferStatus(str, Enum):
    """Statut d'un transfert dans le state store."""

    PENDING = "pending"  # Pas encore traite
    COPYING = "copying"  # Copie en cours (interrompue ?)
    COPIED = "copied"  # Copie ok mais hash non verifie
    VERIFIED = "verified"  # Hash verifie, source pas encore supprimee
    COMMITTED = "committed"  # Source supprimee, symlink swappe : termine
    FAILED_COPY = "failed_copy"
    FAILED_VERIFY = "failed_verify"  # Hash mismatch : destination retiree, source intacte
    FAILED_OTHER = "failed_other"


@dataclass
class MigrationCandidate:
    """
    Un symlink decouvert dans l'arborescence source de la migration.

    Resultat brut du scanner avant arbitrage par note.

    Attributs :
        symlink_path : Chemin du symlink (sur `serveur_fichiers`).
        target_path : Chemin de la cible resolue ou recherchee, ou None si brise.
        media_root : Premier segment metier (Films, Series, Animations, ...).
        relative_category : Chemin relatif sous `media_root` (genre, lettre, etc.).
        size_bytes : Taille de la cible si accessible.
        is_broken : True si le symlink ne resout pas et n'a pu etre retrouve.
        already_on_destination : True si la cible pointe deja vers le nouveau NAS.
    """

    symlink_path: Path
    target_path: Optional[Path]
    media_root: str
    relative_category: str
    size_bytes: Optional[int] = None
    is_broken: bool = False
    already_on_destination: bool = False
    is_symlink: bool = True  # False si le scanner a trouvé un fichier physique au lieu d'un lien
    # Métadonnées techniques extraites par mediainfo (durée surtout, utilisée
    # par le matcher pour discriminer les films homonymes via la formule
    # 50/25/25 + tri par écart de durée TMDB). None tant que l'extracteur
    # n'est pas branché (mode symlinks pur).
    media_info: Optional["MediaInfo"] = None


@dataclass
class RatingDecision:
    """
    Verdict du resolveur de notes pour un candidat.

    Attributs :
        value : Note combinee retenue (echelle 0-10) ou None si introuvable.
        source : Etiquette de la source ayant fourni la note la plus haute.
        imdb : Note IMDb brute si disponible (DB ou dataset).
        tmdb : Note TMDB / TVDB brute si disponible.
        personal : Note personnelle 1-5 brute si disponible (NON renormalisee).
        movie_id_in_db : ID interne de l'entree associee dans `movies` si trouvee.
        series_id_in_db : ID interne de l'entree associee dans `series` si trouvee.
        title_match : Titre canonique trouve en base (utile pour le rapport).
    """

    value: Optional[float] = None
    source: Optional[str] = None
    imdb: Optional[float] = None
    tmdb: Optional[float] = None
    personal: Optional[int] = None
    movie_id_in_db: Optional[int] = None
    series_id_in_db: Optional[int] = None
    title_match: Optional[str] = None


@dataclass
class MatchInfo:
    """
    Resultat de l'identification TMDB/TVDB d'un fichier physique (mode raw).

    Mode symlinks pur : tous les champs restent None / vides (l'oeuvre est
    deja en DB, identifiee par rating_resolver).

    Mode raw : alimente par MigrationMatcher pour decider entre MIGRATE/
    LOW_RATED/UNRATED (match unique avec score >= seuil) et NEEDS_VALIDATION
    (score insuffisant ou candidats multiples).

    Attributs :
        tmdb_id : ID TMDB du match retenu (films ou series).
        tvdb_id : ID TVDB du match retenu (series uniquement).
        score : Score de similarite normalise (0-100) du match retenu.
        top_candidates : Top candidats serialisables (pour CSV NEEDS_VALIDATION
            et debug). Chaque entree contient au minimum {title, year, score,
            tmdb_id?, tvdb_id?}.
    """

    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    score: Optional[float] = None
    top_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MigrationItem:
    """
    Une ligne du plan de migration (un fichier a transferer ou ecarter).

    Sertializee dans le JSON de plan et utilisee par l'executeur de transfert.
    """

    item_id: str  # Identifiant stable (hash du symlink) pour la reprise
    bucket: Bucket
    symlink_path: Path
    source_path: Optional[Path]  # Cible resolue (sur ancien NAS)
    destination_path: Optional[Path]  # Cible prevue (sur nouveau NAS)
    media_root: str
    relative_category: str
    size_bytes: Optional[int]
    rating: RatingDecision
    match: MatchInfo = field(default_factory=MatchInfo)
    is_symlink_source: bool = True  # False = fichier physique brut (mode raw)
    tags: list[str] = field(default_factory=list)


@dataclass
class MigrationStats:
    """Compteurs agreges du plan de migration."""

    total_symlinks: int = 0
    to_migrate: int = 0
    low_rated: int = 0
    unrated: int = 0
    broken: int = 0
    already_on_destination: int = 0
    non_video: int = 0
    not_symlink: int = 0
    needs_validation: int = 0
    already_in_library: int = 0
    total_size_bytes: int = 0  # Cumul des tailles des items "migrate"


@dataclass
class MigrationPlan:
    """
    Plan complet : configuration + statistiques + liste des items.

    Format de serialisation versionne (`version=1`) pour faciliter les
    evolutions ulterieures.
    """

    version: int = 1
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_root: Path = Path(".")
    destination_root: Path = Path(".")
    threshold: float = 0.0
    rating_strategy: str = "max"
    stats: MigrationStats = field(default_factory=MigrationStats)
    items: list[MigrationItem] = field(default_factory=list)


@dataclass
class TransferOutcome:
    """Resultat d'un transfert individuel."""

    item_id: str
    status: TransferStatus
    source_hash: Optional[str] = None
    destination_hash: Optional[str] = None
    error_message: Optional[str] = None
    bytes_transferred: int = 0
