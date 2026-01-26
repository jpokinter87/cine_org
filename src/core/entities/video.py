"""
Entités fichier vidéo.

Entités représentant les fichiers vidéo dans le système, incluant leurs métadonnées
et leur statut de validation durant le workflow de matching.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from src.core.value_objects import MediaInfo


class ValidationStatus(Enum):
    """Statut d'une validation en attente."""

    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass
class VideoFile:
    """
    Représente un fichier vidéo avec ses métadonnées.

    Un VideoFile est l'entité principale suivie à travers tout le workflow :
    scan, parsing, matching, renommage et organisation.

    Attributs :
        id : Identifiant unique (UUID ou ID base de données)
        path : Chemin actuel du fichier sur le disque
        filename : Nom de fichier original (sans le chemin)
        size_bytes : Taille du fichier en octets
        file_hash : Hash du contenu pour la déduplication (SHA-256)
        media_info : Métadonnées techniques extraites via mediainfo
        created_at : Date de création de l'enregistrement
        updated_at : Date de dernière modification de l'enregistrement
    """

    id: Optional[str] = None
    path: Optional[Path] = None
    filename: str = ""
    size_bytes: int = 0
    file_hash: Optional[str] = None
    media_info: Optional[MediaInfo] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PendingValidation:
    """
    Un fichier vidéo en attente de validation utilisateur.

    Quand le matching automatique n'atteint pas le seuil de confiance (85%),
    le fichier entre dans un état de validation en attente où l'utilisateur
    doit sélectionner la bonne correspondance parmi les candidats.

    Attributs :
        id : Identifiant unique
        video_file : Le fichier vidéo en cours de validation
        candidates : Liste des correspondances potentielles depuis les recherches API
        auto_validated : Si le système a auto-validé (score >= 85%)
        validation_status : Statut actuel (pending, validated, rejected)
        selected_candidate_id : ID du candidat choisi par l'utilisateur
        created_at : Date de création de la validation
    """

    id: Optional[str] = None
    video_file: Optional[VideoFile] = None
    candidates: list[Any] = field(default_factory=list)
    auto_validated: bool = False
    validation_status: ValidationStatus = ValidationStatus.PENDING
    selected_candidate_id: Optional[str] = None
    created_at: Optional[datetime] = None
