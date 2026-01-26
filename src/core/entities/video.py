"""
Video file entities.

Entities representing video files in the system, including their metadata
and validation status during the matching workflow.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from src.core.value_objects import MediaInfo


class ValidationStatus(Enum):
    """Status of a pending validation."""

    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass
class VideoFile:
    """
    Represents a video file with its metadata.

    A VideoFile is the core entity tracked through the entire workflow:
    scanning, parsing, matching, renaming, and organizing.

    Attributes:
        id: Unique identifier (UUID or database ID)
        path: Current file path on disk
        filename: Original filename (without path)
        size_bytes: File size in bytes
        file_hash: Content hash for deduplication (SHA-256)
        media_info: Technical metadata extracted via mediainfo
        created_at: When the record was created
        updated_at: When the record was last updated
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
    A video file awaiting user validation.

    When automatic matching doesn't meet the confidence threshold (85%),
    the file enters a pending validation state where the user must
    select the correct match from candidates.

    Attributes:
        id: Unique identifier
        video_file: The video file being validated
        candidates: List of potential matches from API searches
        auto_validated: Whether the system auto-validated (score >= 85%)
        validation_status: Current status (pending, validated, rejected)
        selected_candidate_id: ID of the candidate chosen by user
        created_at: When validation was created
    """

    id: Optional[str] = None
    video_file: Optional[VideoFile] = None
    candidates: list[Any] = field(default_factory=list)
    auto_validated: bool = False
    validation_status: ValidationStatus = ValidationStatus.PENDING
    selected_candidate_id: Optional[str] = None
    created_at: Optional[datetime] = None
