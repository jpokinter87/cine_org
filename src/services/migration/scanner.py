"""
Scanner pour la migration depuis d'anciens NAS.

Parcourt l'arborescence de symlinks "source" et produit un MigrationCandidate
par fichier vidéo découvert. Le scanner ne fait aucune décision métier (filtrage
par note, choix de destination) : il extrait l'info brute (cible résolue,
catégorie, taille) et tagge les cas particuliers (lien brisé, fichier déjà
sur destination, fichier physique au lieu de symlink).

Utilisation :
    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTENSIONS,
        destination_root=Path("/media/NAS64"),
        alternative_roots=[Path("/media/usb1/Vidéo_usb1"), ...],
    )
    for candidate in scanner.scan(Path("/media/Serveur/Vidéos")):
        ...
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Optional

from src.services.migration.dataclasses import MigrationCandidate


class MigrationScanner:
    """
    Walker de l'arborescence source.

    Args:
        video_extensions: Extensions de fichiers à inclure (ex: VIDEO_EXTENSIONS).
        destination_root: Si fourni, sert à détecter les symlinks dont la
            cible est déjà sur le nouveau NAS (bucket already_on_destination).
        alternative_roots: Racines à explorer pour retrouver une cible quand
            un symlink est cassé (le fichier physique a été déplacé sur un
            autre disque).
    """

    def __init__(
        self,
        video_extensions: Iterable[str],
        destination_root: Optional[Path] = None,
        alternative_roots: Optional[Iterable[Path]] = None,
    ) -> None:
        self._video_extensions = frozenset(e.lower() for e in video_extensions)
        self._destination_root = (
            destination_root.resolve() if destination_root else None
        )
        self._alternative_roots = (
            [Path(r) for r in alternative_roots] if alternative_roots else []
        )
        # Cache des index alt_root -> {filename: full_path} pour éviter de
        # re-scanner les disques de secours à chaque lien cassé.
        self._alt_index_cache: dict[Path, dict[str, Path]] = {}

    def scan(self, root: Path) -> Iterator[MigrationCandidate]:
        """
        Itère sur tous les fichiers vidéo sous `root` et produit un candidat
        par entrée. Les fichiers d'extension non vidéo sont silencieusement
        ignorés (cas typique : fichiers .nfo, .txt, posters, etc.).
        """
        root = Path(root)
        for dirpath, _, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                full = Path(dirpath) / name
                if full.suffix.lower() not in self._video_extensions:
                    continue
                yield self._classify(full, root)

    def _classify(self, path: Path, root: Path) -> MigrationCandidate:
        media_root, relative_category = self._extract_categories(path, root)

        if not path.is_symlink():
            # Fichier physique sous le root de migration : potentiellement
            # à migrer aussi, mais signalé pour traitement manuel.
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            return MigrationCandidate(
                symlink_path=path,
                target_path=path,
                media_root=media_root,
                relative_category=relative_category,
                size_bytes=size,
                is_broken=False,
                already_on_destination=False,
                is_symlink=False,
            )

        # Symlink : tenter de résoudre la cible.
        target = self._resolve_target(path)
        is_broken = target is None
        already_on_destination = bool(
            target
            and self._destination_root
            and self._is_under(target, self._destination_root)
        )
        size: Optional[int] = None
        if target is not None and target.exists():
            try:
                size = target.stat().st_size
            except OSError:
                size = None

        return MigrationCandidate(
            symlink_path=path,
            target_path=target,
            media_root=media_root,
            relative_category=relative_category,
            size_bytes=size,
            is_broken=is_broken,
            already_on_destination=already_on_destination,
            is_symlink=True,
        )

    def _resolve_target(self, symlink: Path) -> Optional[Path]:
        """Suit le symlink, puis fallback sur la recherche dans alternative_roots."""
        try:
            raw = Path(os.readlink(symlink))
        except OSError:
            return None
        candidate = (
            raw if raw.is_absolute() else (symlink.parent / raw).resolve(strict=False)
        )
        if candidate.exists():
            try:
                return candidate.resolve()
            except OSError:
                return candidate

        # Fallback : chercher par nom de fichier dans les roots alternatifs.
        for alt in self._alternative_roots:
            index = self._index_for(alt)
            found = index.get(candidate.name)
            if found is not None:
                return found
        return None

    def _index_for(self, root: Path) -> dict[str, Path]:
        cached = self._alt_index_cache.get(root)
        if cached is not None:
            return cached
        index: dict[str, Path] = {}
        if root.exists():
            for dirpath, _, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    # Premier vu gagne (suffisant pour les NAS où les noms
                    # sont uniques par dossier).
                    index.setdefault(name, Path(dirpath) / name)
        self._alt_index_cache[root] = index
        return index

    @staticmethod
    def _extract_categories(path: Path, root: Path) -> tuple[str, str]:
        """
        Retourne (media_root, relative_category).

        media_root = premier segment sous `root` (ex: "Films", "Séries").
        relative_category = chemin relatif de `path.parent` sous media_root.
        """
        try:
            rel = path.relative_to(root)
        except ValueError:
            return "", ""
        parts = rel.parts
        if len(parts) <= 1:
            # Fichier directement dans root : pas de catégorie
            return "", ""
        media_root = parts[0]
        # parent.relative_to(root / media_root) — exclure le nom du fichier
        category_parts = parts[1:-1]
        return media_root, "/".join(category_parts)

    @staticmethod
    def _is_under(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent)
            return True
        except ValueError:
            return False
