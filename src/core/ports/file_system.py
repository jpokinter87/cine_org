"""
File system port interfaces.

Abstract interfaces (ports) defining contracts for file operations.
Implementations (adapters) will provide concrete file system access
and symlink management.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core.value_objects import MediaInfo


class IFileSystem(ABC):
    """
    Basic file operations interface.

    Defines operations for interacting with the file system:
    checking existence, reading metadata, moving/copying files.
    """

    @abstractmethod
    def exists(self, path: Path) -> bool:
        """Check if a path exists."""
        ...

    @abstractmethod
    def read_metadata(self, path: Path) -> Optional[MediaInfo]:
        """
        Read technical metadata from a video file.

        Uses mediainfo to extract resolution, codecs, languages, duration.

        Args:
            path: Path to the video file

        Returns:
            MediaInfo with extracted metadata, or None if extraction fails
        """
        ...

    @abstractmethod
    def move(self, source: Path, destination: Path) -> bool:
        """
        Move a file from source to destination.

        Creates parent directories if needed.

        Args:
            source: Current file path
            destination: Target file path

        Returns:
            True if successful, False otherwise
        """
        ...

    @abstractmethod
    def copy(self, source: Path, destination: Path) -> bool:
        """
        Copy a file from source to destination.

        Creates parent directories if needed.

        Args:
            source: Source file path
            destination: Target file path

        Returns:
            True if successful, False otherwise
        """
        ...

    @abstractmethod
    def delete(self, path: Path) -> bool:
        """
        Delete a file.

        Args:
            path: Path to delete

        Returns:
            True if deleted, False otherwise
        """
        ...

    @abstractmethod
    def calculate_hash(self, path: Path) -> Optional[str]:
        """
        Calculate content hash (SHA-256) for deduplication.

        Args:
            path: Path to the file

        Returns:
            Hex-encoded SHA-256 hash, or None if calculation fails
        """
        ...

    @abstractmethod
    def get_size(self, path: Path) -> int:
        """
        Get file size in bytes.

        Args:
            path: Path to the file

        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        ...


class ISymlinkManager(ABC):
    """
    Symlink management interface.

    Defines operations for creating and managing symbolic links.
    Used for the video/ directory that mirrors storage/ structure.
    """

    @abstractmethod
    def create_symlink(self, target: Path, link: Path) -> bool:
        """
        Create a symbolic link.

        Args:
            target: Path the symlink points to (the actual file)
            link: Path where the symlink will be created

        Returns:
            True if created successfully, False otherwise
        """
        ...

    @abstractmethod
    def remove_symlink(self, link: Path) -> bool:
        """
        Remove a symbolic link.

        Args:
            link: Path to the symlink to remove

        Returns:
            True if removed, False otherwise
        """
        ...

    @abstractmethod
    def is_symlink(self, path: Path) -> bool:
        """Check if a path is a symbolic link."""
        ...

    @abstractmethod
    def resolve_target(self, link: Path) -> Optional[Path]:
        """
        Resolve the target of a symbolic link.

        Args:
            link: Path to the symlink

        Returns:
            Resolved target path, or None if not a symlink or broken
        """
        ...

    @abstractmethod
    def find_broken_links(self, directory: Path) -> list[Path]:
        """
        Find all broken symbolic links in a directory (recursive).

        Args:
            directory: Directory to search

        Returns:
            List of paths to broken symlinks
        """
        ...
