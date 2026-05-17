"""Résolution d'un ``MissingRecord`` via les symlinks de ``video_dir``.

Quand un film a été déplacé manuellement dans ``storage/`` (ou par un script
de réorganisation), son ``file_path`` en DB est obsolète. Mais si le symlink
dans ``video/`` a été mis à jour (ou recréé par ``reconcile``/``repair-links``)
et pointe correctement vers la nouvelle cible storage, alors :

1. Le symlink ``video/.../Title (Year).mkv`` existe.
2. Il n'est pas cassé (resolve() réussit).
3. Sa cible est la vraie position du fichier.

C'est ce signal qu'on utilise. Stratégie V1 :

* Indexe les symlinks vivants de ``video_dir`` par leur basename.
* Pour chaque ``MissingRecord``, retourne les cibles (uniques) des symlinks
  dont le basename correspond à celui du ``file_path`` stale.

La zone ``storage_dir`` n'est volontairement pas scannée — un fichier qui
serait dans storage sans symlink dans video n'est plus dans la bibliothèque
côté utilisateur ; le repair ne ferait que recâbler vers un fichier
inaccessible. Mieux vaut le ``--prune`` puis ré-importer.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from src.infrastructure.persistence.models import EpisodeModel, MovieModel
from src.services.missing_files_scanner import MissingRecord


class MissingFileResolver:
    """Indexe les symlinks vivants de ``video_dir`` et résout par basename."""

    def __init__(self, video_dir: Path | None) -> None:
        self._video_dir = Path(video_dir) if video_dir else None
        self._index: Optional[dict[str, set[Path]]] = None

    def _build_index(self) -> dict[str, set[Path]]:
        """Indexe basename → {cibles storage} pour les symlinks vivants."""
        if self._index is not None:
            return self._index
        index: dict[str, set[Path]] = defaultdict(set)
        if self._video_dir is None or not self._video_dir.exists():
            self._index = dict(index)
            return self._index
        for path in self._video_dir.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                # Symlink cassé ou cycle → on l'ignore.
                continue
            index[path.name].add(resolved)
        self._index = dict(index)
        return self._index

    def find_candidates(self, record: MissingRecord) -> list[Path]:
        """Retourne les cibles storage des symlinks de même basename.

        La cible égale au ``file_path`` stale est filtrée (en pratique impossible
        puisqu'elle n'existe pas, mais on protège contre les races/symlinks
        intermédiaires).
        """
        target_name = Path(record.file_path).name
        if not target_name:
            return []
        stale = Path(record.file_path)
        cands = self._build_index().get(target_name, set())
        return sorted(c for c in cands if c != stale)

    def apply_repair(
        self, session: Session, record: MissingRecord, new_path: Path
    ) -> bool:
        """Réécrit le ``file_path`` en DB vers ``new_path``. Retourne True si OK.

        N'opère aucune modification filesystem : la cible ``new_path`` doit
        déjà exister (c'est garanti par ``find_candidates`` qui ne renvoie
        que des cibles de symlinks vivants).
        """
        if record.entity_type == "movie":
            model = session.get(MovieModel, record.entity_id)
        elif record.entity_type == "episode":
            model = session.get(EpisodeModel, record.entity_id)
        else:
            return False
        if model is None:
            return False
        model.file_path = str(new_path)
        session.add(model)
        session.commit()
        return True
