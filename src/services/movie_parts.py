"""Service de rattachement des parties orphelines de films multi-parties.

Pour chaque symlink ``… Partie N …`` (N >= 2) present dans la zone video,
retrouve le film via le symlink de la Partie 1 (meme nom avec « Partie 1 ») et
cree la ligne MoviePart manquante. Idempotent : ne recree pas une partie deja
enregistree. Le storage n'est jamais modifie.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel

_PART_RE = re.compile(r"(?i)\bPartie\s+(\d+)\b")


@dataclass(frozen=True)
class PartLink:
    """Une partie a rattacher a un film."""

    movie_id: int
    part_number: int
    file_path: str
    symlink_path: str


class MoviePartLinker:
    """Detecte et rattache les parties orphelines (>= 2) dans la zone video."""

    def __init__(self, session: Session, video_dir: Path) -> None:
        self._session = session
        self._video_dir = Path(video_dir)

    def build_plan(self) -> list[PartLink]:
        """Construit la liste des parties a creer (sans rien ecrire)."""
        plan: list[PartLink] = []
        for symlink in sorted(self._video_dir.rglob("*")):
            if not symlink.is_symlink():
                continue
            match = _PART_RE.search(symlink.name)
            if not match:
                continue
            part_number = int(match.group(1))
            if part_number < 2:
                continue

            name_p1 = _PART_RE.sub("Partie 1", symlink.name)
            movie = self._session.exec(
                select(MovieModel).where(
                    MovieModel.symlink_path.like(f"%/{name_p1}")  # type: ignore[union-attr]
                )
            ).first()
            if not movie:
                continue

            existing = self._session.exec(
                select(MoviePartModel).where(
                    MoviePartModel.movie_id == movie.id,
                    MoviePartModel.part_number == part_number,
                )
            ).first()
            if existing:
                continue

            storage = str(symlink.resolve())
            plan.append(
                PartLink(
                    movie_id=movie.id,
                    part_number=part_number,
                    file_path=storage,
                    symlink_path=str(symlink),
                )
            )
        return plan

    def apply(self, plan: list[PartLink]) -> int:
        """Cree les lignes MoviePart du plan. Retourne le nombre cree."""
        for link in plan:
            self._session.add(
                MoviePartModel(
                    movie_id=link.movie_id,
                    part_number=link.part_number,
                    file_path=link.file_path,
                    symlink_path=link.symlink_path,
                )
            )
        if plan:
            self._session.commit()
        return len(plan)
