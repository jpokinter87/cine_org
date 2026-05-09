"""
Service de migration depuis d'anciens NAS vers le nouveau NAS.

Ce service prend en charge le transfert controle de fichiers video situes
sur des volumes externes (anciens NAS, disques USB) vers la zone de
stockage principale, en filtrant selon une note minimale combinee
(IMDb / TMDB / personnelle) et en garantissant l'integrite via xxhash.

Le flux est en deux phases strictement separees :

* `MigrationPlanBuilder` parcourt l'arborescence de symlinks, classe chaque
  fichier dans un bucket (`migrate`, `low_rated`, `unrated`, `broken`,
  `already_on_destination`) et serialise un plan JSON ainsi que des CSV de
  revue. Aucune operation destructive.
* `MigrationTransferExecutor` consomme le plan, copie chaque fichier vers
  sa destination, verifie le hash xxh3_64 source/destination, ne supprime
  la source qu'apres verification, et tient un etat SQLite reprenable.
"""

from src.services.migration.dataclasses import (
    Bucket,
    MigrationCandidate,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
    TransferStatus,
)

__all__ = [
    "Bucket",
    "MigrationCandidate",
    "MigrationItem",
    "MigrationPlan",
    "MigrationStats",
    "RatingDecision",
    "TransferStatus",
]
