"""
Configuration du logging de l'application via loguru.

Fournit un logging structuré avec :
- Sortie console : lisible par l'humain, colorée, pour la surveillance en temps réel
- Sortie fichier : sérialisée en JSON, avec rotation, pour l'analyse historique
"""

import sys
from pathlib import Path

from loguru import logger


def configure_logging(
    log_level: str = "INFO",
    log_file: Path = Path("logs/cineorg.log"),
    rotation_size: str = "10 MB",
    retention_count: int = 5,
) -> None:
    """Configure le logging de l'application.

    Args :
        log_level : Niveau de log minimum pour la sortie console (DEBUG, INFO, WARNING, ERROR)
        log_file : Chemin vers le fichier de log
        rotation_size : Taille maximale du fichier avant rotation (ex: "10 MB", "1 GB")
        retention_count : Nombre de fichiers rotatifs à conserver

    Le handler console produit des logs colorés lisibles pour la surveillance temps réel.
    Le handler fichier produit des logs sérialisés JSON avec rotation pour l'analyse historique.
    """
    # Supprime le handler par défaut
    logger.remove()

    # Handler console - lisible par l'humain
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # Handler fichier - JSON pour l'analyse
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",  # Capture tous les niveaux (logs API en DEBUG)
        format="{message}",
        serialize=True,  # Sortie JSON
        rotation=rotation_size,
        retention=retention_count,
        compression="zip",
        enqueue=True,  # Thread-safe
    )

    logger.debug("Logging configuré", log_file=str(log_file), rotation=rotation_size)
