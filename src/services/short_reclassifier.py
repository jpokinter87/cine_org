"""Reclassement des films existants en courts-métrages (phase P3).

Détecte les films de la DB qui correspondent au critère court-métrage (durée
courte, hors arborescence Séries/) et migre leur symlink dans ``video/`` vers
``Films/Courts/{franchise}/``. Le storage physique n'est pas touché : seul le
symlink est déplacé et la cible reste la même.

L'usage typique :

    reclassifier = ShortReclassifier(session, video_dir, threshold_seconds)
    for candidate in reclassifier.find_candidates():
        result = reclassifier.apply(candidate)
        ...

Le service est volontairement minimaliste — la CLI (``cineorg reclassify-shorts``)
gère le dry-run, l'affichage tabulaire et la confirmation utilisateur.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from src.core.entities.media import Movie
from src.core.value_objects import MediaInfo, MediaType
from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel
from src.services.classification import classify_media
from src.services.organizer import get_short_video_destination


@dataclass(frozen=True)
class ShortCandidate:
    """Film candidat au reclassement : symlink à déplacer + nouvelle destination."""

    model: MovieModel
    current_symlink: Path
    new_symlink: Path


@dataclass(frozen=True)
class ReclassResult:
    """Résultat d'une tentative de reclassement."""

    candidate: ShortCandidate
    moved: bool
    error: Optional[str] = None


def _model_to_movie_for_destination(
    model: MovieModel,
    *,
    local_collection_name: Optional[str] = None,
) -> Movie:
    """Construit une entité Movie minimale, suffisante pour calculer la destination."""
    return Movie(
        id=str(model.id) if model.id else None,
        title=model.title,
        year=model.year,
        collection_name=model.collection_name,
        duration_seconds=model.duration_seconds,
        local_collection_id=model.local_collection_id,
        local_collection_name=local_collection_name,
    )


class ShortReclassifier:
    """Service de reclassement des films courts existants en base."""

    def __init__(
        self,
        session: Session,
        video_dir: Path,
        threshold_seconds: int,
    ) -> None:
        self._session = session
        self._video_dir = video_dir
        self._threshold = threshold_seconds

    def _lookup_local_collection_name(
        self, local_collection_id: Optional[int]
    ) -> Optional[str]:
        """Charge le nom de la collection locale référencée (None si absente)."""
        if local_collection_id is None:
            return None
        coll = self._session.get(LocalCollectionModel, local_collection_id)
        return coll.name if coll else None

    def find_candidates(self) -> list[ShortCandidate]:
        """Liste les films à reclasser en court-métrage.

        Sélectionne les films avec ``duration_seconds <= threshold``, ayant un
        ``symlink_path`` actif, hors de l'arborescence ``Séries/``, et dont le
        symlink actuel ne correspond pas à la destination calculée. Capte donc
        à la fois :

        * les films non encore marqués ``is_short=True`` (migration initiale) ;
        * les films déjà ``is_short=True`` mais dont la franchise a changé
          (P4 : assignation d'une collection locale → déplacement de Divers
          vers la nouvelle franchise).
        """
        stmt = (
            select(MovieModel)
            .where(MovieModel.duration_seconds.isnot(None))
            .where(MovieModel.duration_seconds <= self._threshold)
            .where(MovieModel.symlink_path.isnot(None))
        )
        candidates: list[ShortCandidate] = []
        for model in self._session.exec(stmt).all():
            current = Path(model.symlink_path)
            media_info = MediaInfo(duration_seconds=model.duration_seconds)
            if (
                classify_media(current, media_info, self._threshold)
                is not MediaType.SHORT
            ):
                continue
            local_name = self._lookup_local_collection_name(model.local_collection_id)
            movie = _model_to_movie_for_destination(
                model, local_collection_name=local_name
            )
            new_dir = get_short_video_destination(movie, self._video_dir)
            new_symlink = new_dir / current.name
            if current == new_symlink:
                continue
            candidates.append(
                ShortCandidate(
                    model=model,
                    current_symlink=current,
                    new_symlink=new_symlink,
                )
            )
        return candidates

    def apply(self, candidate: ShortCandidate) -> ReclassResult:
        """Applique le reclassement : déplace le symlink + met à jour la DB.

        Le storage physique n'est jamais touché : on lit la cible du symlink
        actuel, on crée un nouveau symlink à la nouvelle destination pointant
        vers la même cible, puis on supprime l'ancien. La DB est mise à jour
        en dernier (atomicité best-effort).
        """
        source = candidate.current_symlink
        dest = candidate.new_symlink

        if dest.exists() or dest.is_symlink():
            return ReclassResult(
                candidate=candidate,
                moved=False,
                error=f"destination déjà présente : {dest}",
            )

        try:
            target = source.readlink()
        except OSError as exc:
            return ReclassResult(
                candidate=candidate,
                moved=False,
                error=f"lecture symlink source impossible : {exc}",
            )

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(target)
        except OSError as exc:
            return ReclassResult(
                candidate=candidate,
                moved=False,
                error=f"création symlink destination impossible : {exc}",
            )

        try:
            source.unlink()
        except OSError as exc:
            # Rollback : retirer le nouveau symlink pour éviter le doublon
            try:
                dest.unlink()
            except OSError:
                pass
            return ReclassResult(
                candidate=candidate,
                moved=False,
                error=f"suppression symlink source impossible : {exc}",
            )

        candidate.model.is_short = True
        candidate.model.symlink_path = str(dest)
        self._session.add(candidate.model)
        self._session.commit()
        self._session.refresh(candidate.model)

        return ReclassResult(candidate=candidate, moved=True)
