"""
Service de nettoyage et reorganisation du repertoire video.

Detecte et corrige les problemes dans le repertoire video/ :
- Symlinks casses
- Symlinks mal places (mauvais genre/subdivision)
- Repertoires surcharges (>50 fichiers) non subdivises
- Repertoires vides residuels

Scope : symlinks video/ uniquement (pas les fichiers physiques dans storage/).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

from loguru import logger
from sqlmodel import select

from src.core.entities.media import Movie, Series
from src.core.entities.video import VideoFile
from src.infrastructure.persistence.models import MovieModel, EpisodeModel, SeriesModel
from src.services.organizer import _strip_article

MANAGED_SUBDIRS = ("Films", "Séries")


class CleanupStepType(str, Enum):
    """Types de problemes detectes lors du cleanup."""

    BROKEN_SYMLINK = "broken_symlink"
    MISPLACED_SYMLINK = "misplaced_symlink"
    DUPLICATE_SYMLINK = "duplicate_symlink"
    OVERSIZED_DIR = "oversized_dir"
    EMPTY_DIR = "empty_dir"


@dataclass
class BrokenSymlinkInfo:
    """Informations sur un symlink casse avec le meilleur candidat de reparation."""

    symlink_path: Path
    original_target: Path
    best_candidate: Optional[Path] = None
    candidate_score: float = 0.0


@dataclass
class MisplacedSymlink:
    """Symlink valide mais place dans le mauvais repertoire."""

    symlink_path: Path
    target_path: Path
    current_dir: Path
    expected_dir: Path
    media_title: str = ""


@dataclass
class DuplicateSymlink:
    """Symlinks dupliques : plusieurs liens dans le meme repertoire pointant vers le meme fichier."""

    directory: Path
    target_path: Path
    keep: Path
    remove: list[Path]


@dataclass
class SubdivisionPlan:
    """Plan de subdivision d'un repertoire surcharge."""

    parent_dir: Path
    current_count: int
    max_allowed: int
    ranges: list[tuple[str, str]]
    items_to_move: list[tuple[Path, Path]]


@dataclass
class CleanupReport:
    """Rapport complet d'analyse du repertoire video."""

    video_dir: Path
    broken_symlinks: list[BrokenSymlinkInfo]
    misplaced_symlinks: list[MisplacedSymlink]
    oversized_dirs: list[SubdivisionPlan]
    empty_dirs: list[Path]
    duplicate_symlinks: list[DuplicateSymlink] = field(default_factory=list)
    not_in_db_count: int = 0

    @property
    def has_issues(self) -> bool:
        """Retourne True s'il y a au moins un probleme detecte."""
        return self.total_issues > 0

    @property
    def total_issues(self) -> int:
        """Retourne le nombre total de problemes."""
        return (
            len(self.broken_symlinks)
            + len(self.misplaced_symlinks)
            + len(self.duplicate_symlinks)
            + len(self.oversized_dirs)
            + len(self.empty_dirs)
        )


@dataclass
class CleanupResult:
    """Resultat de l'execution des corrections."""

    repaired_symlinks: int = 0
    failed_repairs: int = 0
    broken_symlinks_deleted: int = 0
    moved_symlinks: int = 0
    duplicate_symlinks_removed: int = 0
    subdivisions_created: int = 0
    symlinks_redistributed: int = 0
    empty_dirs_removed: int = 0
    errors: list[str] = field(default_factory=list)


class CleanupService:
    """
    Service de nettoyage et reorganisation du repertoire video.

    Orchestre la detection et correction de tous les problemes
    dans le repertoire video/ en reutilisant les services existants.
    """

    def __init__(
        self,
        repair_service: Any,
        organizer_service: Any,
        video_file_repo: Any,
        movie_repo: Any,
        series_repo: Any,
        episode_repo: Any,
    ) -> None:
        """
        Initialise le service de cleanup.

        Args:
            repair_service: Service de reparation des symlinks (RepairService)
            organizer_service: Service d'organisation (OrganizerService)
            video_file_repo: Repository des fichiers video
            movie_repo: Repository des films
            series_repo: Repository des series
            episode_repo: Repository des episodes
        """
        self._repair_service = repair_service
        self._organizer_service = organizer_service
        self._video_file_repo = video_file_repo
        self._movie_repo = movie_repo
        self._series_repo = series_repo
        self._episode_repo = episode_repo

    def analyze(self, video_dir: Path, max_per_dir: int = 50) -> CleanupReport:
        """
        Analyse le repertoire video et retourne un rapport complet.

        Args:
            video_dir: Repertoire video a analyser.
            max_per_dir: Nombre max de sous-repertoires par repertoire avant subdivision.

        Returns:
            CleanupReport avec tous les problemes detectes.
        """
        broken = self._scan_broken_symlinks(video_dir)
        misplaced_result = self._scan_misplaced_symlinks(video_dir)

        # _scan_misplaced_symlinks retourne (list, int) ou list selon le contexte
        if isinstance(misplaced_result, tuple):
            misplaced, not_in_db = misplaced_result
        else:
            misplaced = misplaced_result
            not_in_db = 0

        duplicates = self._scan_duplicate_symlinks(video_dir)
        oversized = self._scan_oversized_dirs(video_dir, max_per_dir)
        empty = self._scan_empty_dirs(video_dir)

        return CleanupReport(
            video_dir=video_dir,
            broken_symlinks=broken,
            misplaced_symlinks=misplaced,
            duplicate_symlinks=duplicates,
            oversized_dirs=oversized,
            empty_dirs=empty,
            not_in_db_count=not_in_db,
        )

    # ------------------------------------------------------------------
    # Utilitaires scope
    # ------------------------------------------------------------------

    def _iter_managed_paths(self, video_dir: Path) -> Iterator[Path]:
        """Itere recursivement sur les fichiers/dossiers dans Films/ et Series/ uniquement."""
        for subdir_name in MANAGED_SUBDIRS:
            subdir = video_dir / subdir_name
            if subdir.exists():
                yield from subdir.rglob("*")

    def _is_in_managed_scope(self, path: Path, video_dir: Path) -> bool:
        """Verifie si un chemin est sous l'un des sous-repertoires geres."""
        try:
            relative = path.relative_to(video_dir)
        except ValueError:
            return False
        parts = relative.parts
        return len(parts) > 0 and parts[0] in MANAGED_SUBDIRS

    # ------------------------------------------------------------------
    # Analyse
    # ------------------------------------------------------------------

    def _scan_broken_symlinks(self, video_dir: Path) -> list[BrokenSymlinkInfo]:
        """
        Detecte les symlinks casses via RepairService.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Liste de BrokenSymlinkInfo avec le meilleur candidat pour chaque lien.
        """
        broken_links = self._repair_service.find_broken_symlinks()
        result = []

        for link in broken_links:
            # Filtrer les liens hors du scope gere (Films/, Series/)
            if not self._is_in_managed_scope(link, video_dir):
                continue
            # Lire la cible originale
            try:
                original_target = link.readlink()
            except OSError:
                original_target = Path("")

            # Chercher les candidats
            targets = self._repair_service.find_possible_targets(link)

            best_candidate = None
            best_score = 0.0
            if targets:
                best_candidate = targets[0][0]
                best_score = targets[0][1]

            result.append(
                BrokenSymlinkInfo(
                    symlink_path=link,
                    original_target=original_target,
                    best_candidate=best_candidate,
                    candidate_score=best_score,
                )
            )

        return result

    def _scan_misplaced_symlinks(
        self, video_dir: Path
    ) -> tuple[list[MisplacedSymlink], int]:
        """
        Detecte les symlinks valides places dans le mauvais repertoire.

        Pour chaque symlink valide, verifie que son emplacement correspond
        au chemin attendu calcule par OrganizerService.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Tuple (liste de MisplacedSymlink, nombre de symlinks non en BDD).
        """
        misplaced = []
        not_in_db = 0

        for symlink in self._iter_managed_paths(video_dir):
            if not symlink.is_symlink():
                continue

            # Ignorer les symlinks casses
            try:
                target = symlink.resolve()
                if not target.exists():
                    continue
            except OSError:
                continue

            # Chercher en BDD
            video_file = self._video_file_repo.get_by_symlink_path(symlink)
            if video_file is None:
                video_file = self._video_file_repo.get_by_path(target)

            if video_file is None:
                not_in_db += 1
                continue

            # Determiner le type : film ou episode
            expected_dir = self._find_expected_dir(video_file, video_dir)
            if expected_dir is None:
                continue

            # Comparer le repertoire actuel avec le repertoire attendu
            current_dir = symlink.parent
            if current_dir != expected_dir:
                misplaced.append(
                    MisplacedSymlink(
                        symlink_path=symlink,
                        target_path=target,
                        current_dir=current_dir,
                        expected_dir=expected_dir,
                    )
                )

        return misplaced, not_in_db

    def _find_expected_dir(
        self, video_file: VideoFile, video_dir: Path
    ) -> Optional[Path]:
        """
        Calcule le repertoire attendu pour un fichier video.

        Cherche le Movie ou Episode associe et calcule le chemin via OrganizerService.

        Args:
            video_file: Le fichier video.
            video_dir: Repertoire video racine.

        Returns:
            Chemin du repertoire attendu, ou None si non determinable.
        """
        file_path_str = str(video_file.path) if video_file.path else None
        if not file_path_str:
            return None

        # Chercher un film par file_path
        try:
            movie_model = self._movie_repo._session.exec(
                select(MovieModel).where(MovieModel.file_path == file_path_str)
            ).first()

            if movie_model:
                import json
                genres_list = json.loads(movie_model.genres_json) if movie_model.genres_json else []
                movie = Movie(
                    id=str(movie_model.id) if movie_model.id else None,
                    tmdb_id=movie_model.tmdb_id,
                    title=movie_model.title,
                    original_title=movie_model.original_title,
                    year=movie_model.year,
                    genres=tuple(genres_list),
                )
                return self._organizer_service.get_movie_video_destination(movie, video_dir)
        except Exception:
            logger.debug(f"Erreur lors de la recherche du film pour {file_path_str}")

        # Chercher un episode par file_path
        try:
            episode_model = self._episode_repo._session.exec(
                select(EpisodeModel).where(EpisodeModel.file_path == file_path_str)
            ).first()

            if episode_model:
                series_model = self._series_repo._session.exec(
                    select(SeriesModel).where(SeriesModel.id == episode_model.series_id)
                ).first()

                if series_model:
                    import json
                    genres_list = json.loads(series_model.genres_json) if series_model.genres_json else []
                    series = Series(
                        id=str(series_model.id) if series_model.id else None,
                        tvdb_id=series_model.tvdb_id,
                        title=series_model.title,
                        original_title=series_model.original_title,
                        year=series_model.year,
                        genres=tuple(genres_list),
                    )
                    return self._organizer_service.get_series_video_destination(
                        series, episode_model.season_number, video_dir,
                    )
        except Exception:
            logger.debug(f"Erreur lors de la recherche de l'episode pour {file_path_str}")

        return None

    def _scan_duplicate_symlinks(self, video_dir: Path) -> list[DuplicateSymlink]:
        """
        Detecte les symlinks dupliques dans le meme repertoire.

        Deux symlinks sont dupliques s'ils sont dans le meme repertoire
        et pointent vers le meme fichier physique (apres resolution).
        Le symlink a conserver est celui avec le nom le plus long.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Liste de DuplicateSymlink pour chaque groupe de doublons.
        """
        from collections import defaultdict

        # Grouper les symlinks valides par (repertoire, cible resolue)
        groups: dict[tuple[Path, Path], list[Path]] = defaultdict(list)

        for path in self._iter_managed_paths(video_dir):
            if not path.is_symlink():
                continue
            try:
                resolved = path.resolve()
                if not resolved.exists():
                    continue
            except OSError:
                continue
            groups[(path.parent, resolved)].append(path)

        # Pour chaque groupe >= 2, determiner keep/remove
        result = []
        for (directory, target), symlinks in groups.items():
            if len(symlinks) < 2:
                continue
            # Conserver le nom le plus long (plus de metadonnees)
            symlinks.sort(key=lambda p: len(p.name), reverse=True)
            keep = symlinks[0]
            remove = symlinks[1:]
            result.append(
                DuplicateSymlink(
                    directory=directory,
                    target_path=target,
                    keep=keep,
                    remove=remove,
                )
            )

        return result

    def _scan_oversized_dirs(
        self, video_dir: Path, max_per_dir: int = 50
    ) -> list[SubdivisionPlan]:
        """
        Detecte les repertoires avec trop d'elements directs (symlinks + repertoires).

        Exception : les repertoires sous Series/ ne contenant que des symlinks
        (= episodes d'une serie) sont ignores, meme au-dela du seuil.
        Cela protege les series animees avec beaucoup d'episodes sans saisons.

        Args:
            video_dir: Repertoire video a scanner.
            max_per_dir: Seuil d'elements avant subdivision.

        Returns:
            Liste de SubdivisionPlan pour chaque repertoire surcharge.
        """
        plans = []

        for dirpath in self._iter_managed_paths(video_dir):
            if not dirpath.is_dir():
                continue

            # Compter tous les elements directs (symlinks et repertoires)
            items = [
                item for item in dirpath.iterdir()
                if item.is_symlink() or item.is_dir()
            ]

            if not items:
                continue

            # Ignorer les repertoires d'episodes sous Series/
            # (ne contenant que des symlinks = episodes d'une serie)
            has_only_symlinks = all(item.is_symlink() for item in items)
            if has_only_symlinks and self._is_under_series(dirpath, video_dir):
                continue

            if len(items) > max_per_dir:
                plan = self._calculate_subdivision_ranges(dirpath, max_per_dir)
                plans.append(plan)

        return plans

    def _is_under_series(self, path: Path, video_dir: Path) -> bool:
        """Verifie si un chemin est sous le sous-repertoire Series/."""
        try:
            relative = path.relative_to(video_dir)
        except ValueError:
            return False
        parts = relative.parts
        return len(parts) > 0 and parts[0] == "Séries"

    def _scan_empty_dirs(self, video_dir: Path) -> list[Path]:
        """
        Detecte les repertoires vides (bottom-up).

        Un repertoire est vide s'il ne contient ni fichiers ni
        sous-repertoires non-vides. Exclut la racine video_dir.

        Args:
            video_dir: Repertoire video a scanner.

        Returns:
            Liste des repertoires vides.
        """
        empty = []

        # Parcours bottom-up : trier par profondeur decroissante
        all_dirs = sorted(
            [d for d in self._iter_managed_paths(video_dir) if d.is_dir()],
            key=lambda p: len(p.parts),
            reverse=True,
        )

        for dirpath in all_dirs:
            # Exclure la racine
            if dirpath == video_dir:
                continue

            # Verifier si le repertoire est vide
            try:
                contents = list(dirpath.iterdir())
                if not contents:
                    empty.append(dirpath)
            except PermissionError:
                continue

        return empty

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def repair_broken_symlinks(
        self, broken: list[BrokenSymlinkInfo], min_score: float = 90.0
    ) -> CleanupResult:
        """
        Repare les symlinks casses ayant un candidat avec score suffisant.

        Args:
            broken: Liste des symlinks casses a reparer.
            min_score: Score minimum pour auto-reparation.

        Returns:
            CleanupResult avec les compteurs de reparation.
        """
        result = CleanupResult()

        for info in broken:
            if info.best_candidate is None or info.candidate_score < min_score:
                continue

            try:
                success = self._repair_service.repair_symlink(
                    info.symlink_path, info.best_candidate
                )
                if success:
                    result.repaired_symlinks += 1
                else:
                    result.failed_repairs += 1
            except Exception as e:
                result.failed_repairs += 1
                result.errors.append(f"Reparation echouee {info.symlink_path}: {e}")

        return result

    def delete_broken_symlinks(
        self, broken: list[BrokenSymlinkInfo]
    ) -> CleanupResult:
        """
        Supprime les symlinks casses irreparables.

        Utilise apres repair_broken_symlinks pour nettoyer les symlinks
        sans candidat ou avec un score trop faible.

        Args:
            broken: Liste des symlinks casses a supprimer.

        Returns:
            CleanupResult avec le nombre de symlinks supprimes.
        """
        result = CleanupResult()

        for info in broken:
            try:
                info.symlink_path.unlink()
                result.broken_symlinks_deleted += 1
            except FileNotFoundError:
                result.errors.append(f"Symlink deja absent {info.symlink_path}")
            except Exception as e:
                result.errors.append(f"Suppression echouee {info.symlink_path}: {e}")

        return result

    def fix_misplaced_symlinks(
        self, misplaced: list[MisplacedSymlink]
    ) -> CleanupResult:
        """
        Deplace les symlinks mal places vers le bon repertoire.

        Args:
            misplaced: Liste des symlinks a deplacer.

        Returns:
            CleanupResult avec le nombre de symlinks deplaces.
        """
        result = CleanupResult()

        for info in misplaced:
            try:
                info.expected_dir.mkdir(parents=True, exist_ok=True)
                new_path = info.expected_dir / info.symlink_path.name
                info.symlink_path.rename(new_path)
                self._video_file_repo.update_symlink_path(info.symlink_path, new_path)
                result.moved_symlinks += 1
            except Exception as e:
                result.errors.append(f"Deplacement echoue {info.symlink_path}: {e}")

        return result

    def fix_duplicate_symlinks(
        self, duplicates: list[DuplicateSymlink]
    ) -> CleanupResult:
        """
        Supprime les symlinks dupliques en ne gardant que le plus complet.

        Args:
            duplicates: Liste des groupes de symlinks dupliques.

        Returns:
            CleanupResult avec le nombre de symlinks supprimes.
        """
        result = CleanupResult()

        for dup in duplicates:
            for link in dup.remove:
                try:
                    link.unlink()
                    result.duplicate_symlinks_removed += 1
                except FileNotFoundError:
                    result.errors.append(f"Symlink deja absent {link}")
                except Exception as e:
                    result.errors.append(f"Suppression echouee {link}: {e}")

        return result

    def subdivide_oversized_dirs(
        self, plans: list[SubdivisionPlan]
    ) -> CleanupResult:
        """
        Subdivise les repertoires surcharges selon les plans fournis.

        Args:
            plans: Liste des plans de subdivision.

        Returns:
            CleanupResult avec les compteurs de subdivision.
        """
        result = CleanupResult()

        for plan in plans:
            try:
                # Creer les sous-repertoires
                dest_dirs = set()
                for _, dest in plan.items_to_move:
                    dest_dirs.add(dest.parent)

                for dest_dir in dest_dirs:
                    dest_dir.mkdir(parents=True, exist_ok=True)

                # Deplacer les symlinks
                for source, dest in plan.items_to_move:
                    try:
                        source.rename(dest)
                        self._video_file_repo.update_symlink_path(source, dest)
                        result.symlinks_redistributed += 1
                    except Exception as e:
                        result.errors.append(f"Deplacement echoue {source}: {e}")

                result.subdivisions_created += 1
            except Exception as e:
                result.errors.append(f"Subdivision echouee {plan.parent_dir}: {e}")

        return result

    def clean_empty_dirs(self, empty_dirs: list[Path]) -> CleanupResult:
        """
        Supprime les repertoires vides.

        Args:
            empty_dirs: Liste des repertoires vides a supprimer.

        Returns:
            CleanupResult avec le nombre de repertoires supprimes.
        """
        result = CleanupResult()

        # Trier par profondeur decroissante pour supprimer les plus profonds d'abord
        sorted_dirs = sorted(empty_dirs, key=lambda p: len(p.parts), reverse=True)

        for dirpath in sorted_dirs:
            try:
                dirpath.rmdir()
                result.empty_dirs_removed += 1
            except OSError as e:
                result.errors.append(f"Suppression echouee {dirpath}: {e}")

        return result

    # ------------------------------------------------------------------
    # Algorithme de subdivision
    # ------------------------------------------------------------------

    def _calculate_subdivision_ranges(
        self, parent_dir: Path, max_per_subdir: int
    ) -> SubdivisionPlan:
        """
        Calcule les plages de subdivision pour un repertoire surcharge.

        Args:
            parent_dir: Repertoire a subdiviser.
            max_per_subdir: Nombre max d'elements par sous-repertoire.

        Returns:
            SubdivisionPlan avec les plages et les mouvements.
        """
        # Lister les elements directs (symlinks ou dossiers)
        items = sorted(parent_dir.iterdir())
        items = [i for i in items if i.is_symlink() or i.is_dir()]

        # Pour chaque item, calculer la cle de tri (2 lettres)
        keyed: list[tuple[str, Path]] = []
        for item in items:
            title = item.name
            stripped = _strip_article(title).strip()
            if len(stripped) >= 2:
                sort_key = stripped.upper()[:2]
            else:
                sort_key = stripped.upper().ljust(2, "A")
            keyed.append((sort_key, item))

        keyed.sort(key=lambda x: x[0])

        # Diviser en groupes de taille max_per_subdir
        ranges: list[tuple[str, str]] = []
        moves: list[tuple[Path, Path]] = []

        for i in range(0, len(keyed), max_per_subdir):
            group = keyed[i: i + max_per_subdir]
            start = group[0][0][0] + group[0][0][1:].lower()
            end = group[-1][0][0] + group[-1][0][1:].lower()
            range_label = f"{start}-{end}"
            dest = parent_dir / range_label

            for _, item in group:
                moves.append((item, dest / item.name))

            ranges.append((start, end))

        return SubdivisionPlan(
            parent_dir=parent_dir,
            current_count=len(keyed),
            max_allowed=max_per_subdir,
            ranges=ranges,
            items_to_move=moves,
        )


# ------------------------------------------------------------------
# Cache du rapport d'analyse
# ------------------------------------------------------------------

_DEFAULT_CACHE_DIR = Path.home() / ".cineorg"
_CACHE_FILENAME = "cleanup_report.json"


def save_report_cache(
    report: CleanupReport, cache_dir: Optional[Path] = None
) -> None:
    """
    Sauvegarde le rapport d'analyse en JSON pour reutilisation ulterieure.

    Args:
        report: Le rapport a sauvegarder.
        cache_dir: Repertoire du cache (defaut: ~/.cineorg).
    """
    import json

    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / _CACHE_FILENAME

    data = {
        "video_dir": str(report.video_dir),
        "not_in_db_count": report.not_in_db_count,
        "broken_symlinks": [
            {
                "symlink_path": str(b.symlink_path),
                "original_target": str(b.original_target),
                "best_candidate": str(b.best_candidate) if b.best_candidate else None,
                "candidate_score": b.candidate_score,
            }
            for b in report.broken_symlinks
        ],
        "misplaced_symlinks": [
            {
                "symlink_path": str(m.symlink_path),
                "target_path": str(m.target_path),
                "current_dir": str(m.current_dir),
                "expected_dir": str(m.expected_dir),
                "media_title": m.media_title,
            }
            for m in report.misplaced_symlinks
        ],
        "oversized_dirs": [
            {
                "parent_dir": str(o.parent_dir),
                "current_count": o.current_count,
                "max_allowed": o.max_allowed,
                "ranges": o.ranges,
                "items_to_move": [
                    [str(src), str(dst)] for src, dst in o.items_to_move
                ],
            }
            for o in report.oversized_dirs
        ],
        "empty_dirs": [str(d) for d in report.empty_dirs],
        "duplicate_symlinks": [
            {
                "directory": str(d.directory),
                "target_path": str(d.target_path),
                "keep": str(d.keep),
                "remove": [str(r) for r in d.remove],
            }
            for d in report.duplicate_symlinks
        ],
    }

    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def load_report_cache(
    video_dir: Path,
    max_age_minutes: int = 10,
    cache_dir: Optional[Path] = None,
) -> Optional[CleanupReport]:
    """
    Charge le rapport d'analyse depuis le cache s'il existe et est recent.

    Args:
        video_dir: Repertoire video attendu (doit correspondre au cache).
        max_age_minutes: Age maximum du cache en minutes.
        cache_dir: Repertoire du cache (defaut: ~/.cineorg).

    Returns:
        CleanupReport si le cache est valide, None sinon.
    """
    import json
    import time

    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / _CACHE_FILENAME

    if not cache_file.exists():
        return None

    # Verifier l'age du cache
    age_seconds = time.time() - cache_file.stat().st_mtime
    if age_seconds > max_age_minutes * 60:
        return None

    try:
        data = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Verifier que le video_dir correspond
    if data.get("video_dir") != str(video_dir):
        return None

    broken = [
        BrokenSymlinkInfo(
            symlink_path=Path(b["symlink_path"]),
            original_target=Path(b["original_target"]),
            best_candidate=Path(b["best_candidate"]) if b["best_candidate"] else None,
            candidate_score=b["candidate_score"],
        )
        for b in data.get("broken_symlinks", [])
    ]

    misplaced = [
        MisplacedSymlink(
            symlink_path=Path(m["symlink_path"]),
            target_path=Path(m["target_path"]),
            current_dir=Path(m["current_dir"]),
            expected_dir=Path(m["expected_dir"]),
            media_title=m.get("media_title", ""),
        )
        for m in data.get("misplaced_symlinks", [])
    ]

    oversized = [
        SubdivisionPlan(
            parent_dir=Path(o["parent_dir"]),
            current_count=o["current_count"],
            max_allowed=o["max_allowed"],
            ranges=[tuple(r) for r in o["ranges"]],
            items_to_move=[
                (Path(pair[0]), Path(pair[1])) for pair in o["items_to_move"]
            ],
        )
        for o in data.get("oversized_dirs", [])
    ]

    empty = [Path(d) for d in data.get("empty_dirs", [])]

    duplicates = [
        DuplicateSymlink(
            directory=Path(d["directory"]),
            target_path=Path(d["target_path"]),
            keep=Path(d["keep"]),
            remove=[Path(r) for r in d["remove"]],
        )
        for d in data.get("duplicate_symlinks", [])
    ]

    return CleanupReport(
        video_dir=Path(data["video_dir"]),
        broken_symlinks=broken,
        misplaced_symlinks=misplaced,
        duplicate_symlinks=duplicates,
        oversized_dirs=oversized,
        empty_dirs=empty,
        not_in_db_count=data.get("not_in_db_count", 0),
    )
