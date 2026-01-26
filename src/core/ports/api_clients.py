"""API client port interfaces."""

from abc import ABC
from dataclasses import dataclass


@dataclass
class SearchResult:
    """Search result from API."""

    pass  # Will be implemented in Task 3


@dataclass
class MediaDetails:
    """Detailed media information from API."""

    pass  # Will be implemented in Task 3


class IMediaAPIClient(ABC):
    """Base interface for media metadata APIs."""

    pass  # Will be implemented in Task 3
