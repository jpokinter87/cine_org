"""Résolution d'un ``MissingRecord`` vers un fichier réel déplacé ailleurs.

Cas typique : un film a été déplacé manuellement ou par un script de
réorganisation. Son ``file_path`` en DB est obsolète mais le fichier
existe encore quelque part dans la zone storage/video, avec le même
basename (le renamer produit un nom déterministe).

Stratégie V1 — recherche par basename exact :

1. Indexe tous les fichiers et symlinks sous les répertoires fournis
   (un seul ``rglob`` partagé entre tous les records).
2. Pour chaque ``MissingRecord``, retourne les chemins dont le ``Path.name``
   est identique à celui de ``record.file_path`` (en excluant le chemin
   stale lui-même).

Si le basename a changé (renommage manuel), la recherche échoue et l'utilisateur
peut toujours basculer sur ``--prune`` pour archiver la fiche.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from src.infrastructure.persistence.models import EpisodeModel, MovieModel
from src.services.missing_files_scanner import MissingRecord


class MissingFileResolver:
    """Indexe storage/video et retrouve les fichiers déplacés par basename."""

    def __init__(self, search_dirs: list[Path]) -> None:
        self._search_dirs = [Path(d) for d in search_dirs if Path(d).exists()]
        self._index: Optional[dict[str, list[Path]]] = None

    def _build_index(self) -> dict[str, list[Path]]:
        """Index basename → [paths]. Construit à la demande, mis en cache."""
        if self._index is not None:
            return self._index
        index: dict[str, list[Path]] = defaultdict(list)
        for root in self._search_dirs:
            for path in root.rglob("*"):
                # is_file() suit le symlink → True quand cible existe.
                # On veut aussi indexer les symlinks même cassés pour le diagnostic.
                if path.is_file() or path.is_symlink():
                    index[path.name].append(path)
        self._index = dict(index)
        return self._index

    def find_candidates(self, record: MissingRecord) -> list[Path]:
        """Retourne les chemins partageant le basename de ``record.file_path``.

        Le chemin stale lui-même (qui en pratique n'existe pas mais on filtre
        au cas où) est exclu.
        """
        target_name = Path(record.file_path).name
        if not target_name:
            return []
        stale = Path(record.file_path).resolve(strict=False)
        candidates = self._build_index().get(target_name, [])
        return [c for c in candidates if c.resolve(strict=False) != stale]

    def apply_repair(
        self, session: Session, record: MissingRecord, new_path: Path
    ) -> bool:
        """Réécrit le ``file_path`` en DB vers ``new_path``. Retourne True si OK.

        N'opère aucune modification filesystem : la cible ``new_path`` doit
        déjà exister (sinon on aurait un nouveau missing_file). La fiche
        ``VideoFileModel`` éventuelle est laissée en l'état — un futur
        ``reconcile`` ou ``repair-links`` la traitera.
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
