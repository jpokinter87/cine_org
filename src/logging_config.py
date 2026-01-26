"""
Application logging configuration using loguru.

Provides structured logging with:
- Console output: human-readable, colored, for real-time monitoring
- File output: JSON serialized, rotated, for historical analysis
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
    """Configure application logging.

    Args:
        log_level: Minimum log level for console output (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to the log file
        rotation_size: Maximum file size before rotation (e.g., "10 MB", "1 GB")
        retention_count: Number of rotated files to keep

    Console handler outputs human-readable colored logs for real-time monitoring.
    File handler outputs JSON-serialized logs with rotation for historical analysis.
    """
    # Remove default handler
    logger.remove()

    # Console handler - human readable
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

    # File handler - JSON for analysis
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",  # Capture all levels (API logs at DEBUG)
        format="{message}",
        serialize=True,  # JSON output
        rotation=rotation_size,
        retention=retention_count,
        compression="zip",
        enqueue=True,  # Thread-safe
    )

    logger.debug("Logging configured", log_file=str(log_file), rotation=rotation_size)
