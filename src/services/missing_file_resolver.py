"""Résolution d'un ``MissingRecord`` via les symlinks vivants de ``video_dir``.

Quand un film a été déplacé ou renommé, son ``file_path`` en DB est obsolète.
Mais si un symlink dans ``video/`` pointe correctement vers la nouvelle
cible storage, on peut recâbler la DB sans rien toucher au filesystem.

Deux passes de matching :

1. **Basename exact** : cas le plus fiable, traité en priorité.
2. **Tokens titre + année / SxxExx** : fallback quand le renamer a modifié
   le nom du fichier entre l'import (basename obsolète en DB) et le scan
   (symlink avec le nouveau nom). Tokens normalisés (accents, ligatures,
   ponctuation) puis présence vérifiée dans le nom du symlink.

La zone ``storage_dir`` n'est volontairement pas scannée — un fichier qui
serait dans storage sans symlink dans video n'est plus dans la bibliothèque
côté utilisateur ; le repair ne ferait que recâbler vers un fichier
inaccessible. Mieux vaut le ``--prune`` puis ré-importer.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from src.infrastructure.persistence.models import EpisodeModel, MovieModel
from src.services.missing_files_scanner import MissingRecord


def _normalize_text(text: str) -> str:
    """Lowercase + strip diacritics + remplace ponctuation par espace."""
    if not text:
        return ""
    # Ligatures FR avant NFKD (sinon œ devient deux glyphes décomposés)
    text = text.replace("œ", "oe").replace("Œ", "oe")
    text = text.replace("æ", "ae").replace("Æ", "ae")
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lower = no_accents.lower()
    clean = "".join(c if c.isalnum() or c.isspace() else " " for c in lower)
    return " ".join(clean.split())


class _IndexedSymlink:
    """Entrée d'index : nom brut, nom normalisé, cible storage."""

    __slots__ = ("name", "normalized", "target")

    def __init__(self, name: str, normalized: str, target: Path) -> None:
        self.name = name
        self.normalized = normalized
        self.target = target


class MissingFileResolver:
    """Indexe les symlinks vivants de ``video_dir`` et résout par basename
    puis par tokens titre/année (fallback)."""

    def __init__(self, video_dir: Path | None) -> None:
        self._video_dir = Path(video_dir) if video_dir else None
        self._index: Optional[list[_IndexedSymlink]] = None

    def _build_index(self) -> list[_IndexedSymlink]:
        """Construit l'index une seule fois (lazy)."""
        if self._index is not None:
            return self._index
        entries: list[_IndexedSymlink] = []
        if self._video_dir is None or not self._video_dir.exists():
            self._index = entries
            return entries
        for path in self._video_dir.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                # Symlink cassé ou cycle → ignoré.
                continue
            entries.append(
                _IndexedSymlink(
                    name=path.name,
                    normalized=_normalize_text(path.name),
                    target=resolved,
                )
            )
        self._index = entries
        return entries

    def find_candidates(self, record: MissingRecord) -> list[Path]:
        """Retourne les cibles storage des symlinks compatibles.

        Phase 1 : match basename exact (plus fiable).
        Phase 2 : si rien trouvé, fallback tokens (titre + année / SxxExx).
        """
        target_name = Path(record.file_path).name
        stale = Path(record.file_path)
        index = self._build_index()

        # Phase 1 : basename exact
        if target_name:
            exact = {e.target for e in index if e.name == target_name}
            exact.discard(stale)
            if exact:
                return sorted(exact)

        # Phase 2 : tokens titre/année (ou SxxExx pour épisodes)
        tokens = self._tokens_for(record)
        if not tokens:
            return []
        fuzzy = {e.target for e in index if all(tok in e.normalized for tok in tokens)}
        fuzzy.discard(stale)
        return sorted(fuzzy)

    def _tokens_for(self, record: MissingRecord) -> list[str]:
        """Tokens normalisés requis pour la recherche fuzzy."""
        if record.entity_type == "movie":
            title_tokens = _normalize_text(record.title).split()
            if not title_tokens:
                return []
            if record.year:
                return title_tokens + [str(record.year)]
            return title_tokens
        if record.entity_type == "episode":
            if record.season is None or record.episode is None:
                return []
            sxxeyy = f"s{record.season:02d}e{record.episode:02d}"
            series_tokens = _normalize_text(record.series_title or "").split()
            return series_tokens + [sxxeyy]
        return []

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
