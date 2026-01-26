"""Video file entities."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.core.value_objects import MediaInfo


class ValidationStatus(Enum):
    """Status of a pending validation."""

    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass
class VideoFile:
    """Represents a video file with its metadata."""

    pass  # Will be implemented in Task 3


@dataclass
class PendingValidation:
    """A video file awaiting user validation."""

    pass  # Will be implemented in Task 3
