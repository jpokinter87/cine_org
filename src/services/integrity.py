"""
Services de verification d'integrite et reparation de la videotheque.

IntegrityChecker verifie la coherence entre la BDD et le filesystem.
RepairService permet de reparer interactivement les symlinks casses.

Responsabilites IntegrityChecker:
- Detecter les entrees fantomes (BDD sans fichier physique)
- Detecter les fichiers orphelins (physique sans entree BDD)
- Detecter les symlinks casses dans le dossier video
- Generer un rapport avec suggestions de correction

Responsabilites RepairService:
- Trouver les symlinks casses
- Proposer des cibles de reparation (fichiers avec meme nom)
- Reparer ou deplacer les liens orphelins vers trash
- Journaliser les actions effectuees
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class IssueType(str, Enum):
    """Type d'incoherence detectee."""

    GHOST_ENTRY = "ghost_entry"  # Entree BDD sans fichier physique
    ORPHAN_FILE = "orphan_file"  # Fichier physique sans entree BDD
    BROKEN_SYMLINK = "broken_symlink"  # Symlink casse dans video/


class RepairActionType(str, Enum):
    """Type d'action de reparation."""

    REPAIRED = "repaired"  # Symlink recree avec nouvelle cible
    ORPHANED = "orphaned"  # Deplace vers trash/orphans
    SKIPPED = "skipped"  # Ignore par l'utilisateur


@dataclass
class IntegrityIssue:
    """Une incoherence detectee.

    Attributes:
        type: Type de l'incoherence (ghost_entry, orphan_file, broken_symlink)
        path: Chemin concerne
        details: Details supplementaires sur l'incoherence
    """

    type: IssueType
    path: Path
    details: str = ""

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour serialisation JSON."""
        return {
            "type": self.type.value,
            "path": str(self.path),
            "details": self.details,
        }


@dataclass
class IntegrityReport:
    """Rapport d'integrite de la videotheque.

    Attributes:
        issues: Liste des incoherences detectees
        suggestions: Commandes correctives suggerees
        checked_at: Date/heure de la verification
    """

    issues: list[IntegrityIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def has_issues(self) -> bool:
        """Indique si des incoherences ont ete detectees."""
        return len(self.issues) > 0

    @property
    def ghost_entries(self) -> list[IntegrityIssue]:
        """Filtre les entrees fantomes."""
        return [i for i in self.issues if i.type == IssueType.GHOST_ENTRY]

    @property
    def orphan_files(self) -> list[IntegrityIssue]:
        """Filtre les fichiers orphelins."""
        return [i for i in self.issues if i.type == IssueType.ORPHAN_FILE]

    @property
    def broken_symlinks(self) -> list[IntegrityIssue]:
        """Filtre les symlinks casses."""
        return [i for i in self.issues if i.type == IssueType.BROKEN_SYMLINK]

    def to_json(self) -> str:
        """Serialise le rapport en JSON."""
        return json.dumps(
            {
                "checked_at": self.checked_at.isoformat(),
                "has_issues": self.has_issues,
                "summary": {
                    "total": len(self.issues),
                    "ghost_entries": len(self.ghost_entries),
                    "orphan_files": len(self.orphan_files),
                    "broken_symlinks": len(self.broken_symlinks),
                },
                "issues": [i.to_dict() for i in self.issues],
                "suggestions": self.suggestions,
            },
            indent=2,
            ensure_ascii=False,
        )

    def format_text(self) -> str:
        """Formate le rapport en texte structure."""
        lines = []
        lines.append(f"=== Rapport d'integrite ===")
        lines.append(f"Date: {self.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        if not self.has_issues:
            lines.append("Aucune incoherence detectee.")
            return "\n".join(lines)

        lines.append(f"Total: {len(self.issues)} incoherence(s)")
        lines.append("")

        # Entrees fantomes
        if self.ghost_entries:
            lines.append(f"--- Entrees fantomes ({len(self.ghost_entries)}) ---")
            lines.append("Fichiers presents dans la BDD mais absents du disque:")
            for issue in self.ghost_entries:
                lines.append(f"  - {issue.path}")
                if issue.details:
                    lines.append(f"    {issue.details}")
            lines.append("")

        # Fichiers orphelins
        if self.orphan_files:
            lines.append(f"--- Fichiers orphelins ({len(self.orphan_files)}) ---")
            lines.append("Fichiers presents sur disque mais absents de la BDD:")
            for issue in self.orphan_files:
                lines.append(f"  - {issue.path}")
            lines.append("")

        # Symlinks casses
        if self.broken_symlinks:
            lines.append(f"--- Symlinks casses ({len(self.broken_symlinks)}) ---")
            lines.append("Liens symboliques pointant vers des cibles inexistantes:")
            for issue in self.broken_symlinks:
                lines.append(f"  - {issue.path}")
                if issue.details:
                    lines.append(f"    Cible: {issue.details}")
            lines.append("")

        # Suggestions
        if self.suggestions:
            lines.append("--- Suggestions ---")
            for suggestion in self.suggestions:
                lines.append(f"  {suggestion}")

        return "\n".join(lines)


@dataclass
class RepairAction:
    """Action de reparation effectuee.

    Attributes:
        link: Chemin du symlink traite
        action: Type d'action (repaired, orphaned, skipped)
        new_target: Nouvelle cible si reparation
        timestamp: Date/heure de l'action
    """

    link: Path
    action: RepairActionType
    new_target: Optional[Path] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour journalisation."""
        return {
            "link": str(self.link),
            "action": self.action.value,
            "new_target": str(self.new_target) if self.new_target else None,
            "timestamp": self.timestamp.isoformat(),
        }


class IntegrityChecker:
    """
    Verifie la coherence entre la BDD et le filesystem.

    Detecte trois types d'incoherences:
    - Ghost entries: fichiers en BDD mais absents du disque
    - Orphan files: fichiers sur disque mais absents de la BDD
    - Broken symlinks: liens symboliques casses dans video/

    Example:
        checker = IntegrityChecker(
            file_system=fs,
            video_file_repo=repo,
            storage_dir=Path("/storage"),
            video_dir=Path("/video"),
        )
        report = checker.check()
        if report.has_issues:
            print(report.format_text())
    """

    # Extensions video a scanner
    VIDEO_EXTENSIONS = frozenset({
        ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"
    })

    def __init__(
        self,
        file_system: Any,
        video_file_repo: Any,
        storage_dir: Optional[Path] = None,
        video_dir: Optional[Path] = None,
    ) -> None:
        """
        Initialise le verificateur d'integrite.

        Args:
            file_system: Adaptateur filesystem (IFileSystem + ISymlinkManager)
            video_file_repo: Repository des fichiers video
            storage_dir: Dossier de stockage physique (optionnel)
            video_dir: Dossier des symlinks video (optionnel)
        """
        self._file_system = file_system
        self._video_file_repo = video_file_repo
        self._storage_dir = storage_dir
        self._video_dir = video_dir

    def check(self, verify_hash: bool = False) -> IntegrityReport:
        """
        Effectue une verification complete d'integrite.

        Args:
            verify_hash: Si True, verifie aussi les hash de fichiers (lent)

        Returns:
            IntegrityReport avec toutes les incoherences detectees
        """
        report = IntegrityReport()

        # 1. Detecter les entrees fantomes
        self._check_ghost_entries(report)

        # 2. Detecter les fichiers orphelins (si storage_dir configure)
        if self._storage_dir:
            self._check_orphan_files(report)

        # 3. Detecter les symlinks casses (si video_dir configure)
        if self._video_dir:
            self._check_broken_symlinks(report)

        # 4. Verification hash optionnelle
        if verify_hash:
            self._verify_hashes(report)

        # 5. Generer les suggestions
        report.suggestions = self._suggest_fixes(report)

        return report

    def _check_ghost_entries(self, report: IntegrityReport) -> None:
        """Detecte les entrees BDD sans fichier physique."""
        # Recuperer tous les fichiers de la BDD via une methode adaptee
        # Note: Comme le repo n'a pas de list_all(), on utilise une approche alternative
        # On peut acceder a la session directement (compromis acceptable)
        try:
            from sqlmodel import select
            from src.infrastructure.persistence.models import VideoFileModel

            session = self._video_file_repo._session
            statement = select(VideoFileModel)
            models = session.exec(statement).all()

            for model in models:
                if model.path:
                    path = Path(model.path)
                    if not path.exists():
                        report.issues.append(
                            IntegrityIssue(
                                type=IssueType.GHOST_ENTRY,
                                path=path,
                                details=f"ID BDD: {model.id}",
                            )
                        )
        except Exception as e:
            logger.warning(f"Erreur lors de la verification des entrees fantomes: {e}")

    def _check_orphan_files(self, report: IntegrityReport) -> None:
        """Detecte les fichiers physiques sans entree BDD."""
        if not self._storage_dir or not self._storage_dir.exists():
            return

        # Lister tous les fichiers video dans storage
        for video_file in self._storage_dir.rglob("*"):
            if video_file.is_dir():
                continue
            if video_file.is_symlink():
                continue
            if video_file.suffix.lower() not in self.VIDEO_EXTENSIONS:
                continue

            # Verifier si le fichier existe en BDD
            existing = self._video_file_repo.get_by_path(video_file)
            if existing is None:
                report.issues.append(
                    IntegrityIssue(
                        type=IssueType.ORPHAN_FILE,
                        path=video_file,
                    )
                )

    def _check_broken_symlinks(self, report: IntegrityReport) -> None:
        """Detecte les symlinks casses dans video/."""
        if not self._video_dir or not self._video_dir.exists():
            return

        broken_links = self._file_system.find_broken_links(self._video_dir)
        for link in broken_links:
            # Recuperer la cible originale (meme si cassee)
            try:
                original_target = link.readlink()
            except OSError:
                original_target = Path("<inconnu>")

            report.issues.append(
                IntegrityIssue(
                    type=IssueType.BROKEN_SYMLINK,
                    path=link,
                    details=str(original_target),
                )
            )

    def _verify_hashes(self, report: IntegrityReport) -> None:
        """Verifie les hash des fichiers (optionnel, lent)."""
        # Implementation future si necessaire
        pass

    def _suggest_fixes(self, report: IntegrityReport) -> list[str]:
        """Genere les commandes correctives suggerees."""
        suggestions = []

        if report.ghost_entries:
            suggestions.append(
                f"Pour {len(report.ghost_entries)} entree(s) fantome(s): "
                "verifier si les fichiers ont ete deplaces ou supprimes"
            )

        if report.orphan_files:
            suggestions.append(
                f"Pour {len(report.orphan_files)} fichier(s) orphelin(s): "
                "cineorg import pour les ajouter a la BDD"
            )

        if report.broken_symlinks:
            suggestions.append(
                f"Pour {len(report.broken_symlinks)} symlink(s) casse(s): "
                "cineorg repair-links pour les reparer interactivement"
            )

        return suggestions


class RepairService:
    """
    Service de reparation des symlinks casses.

    Permet de reparer interactivement les liens symboliques casses
    en proposant des cibles alternatives ou en les deplacant vers
    le dossier trash/orphans.

    Example:
        repair = RepairService(
            file_system=fs,
            video_file_repo=repo,
            storage_dir=Path("/storage"),
            video_dir=Path("/video"),
            trash_dir=Path("/trash"),
        )
        broken = repair.find_broken_symlinks()
        for link in broken:
            targets = repair.find_possible_targets(link)
            if targets:
                repair.repair_symlink(link, targets[0])
            else:
                repair.move_to_orphans(link)
    """

    def __init__(
        self,
        file_system: Any,
        video_file_repo: Any,
        storage_dir: Optional[Path] = None,
        video_dir: Optional[Path] = None,
        trash_dir: Optional[Path] = None,
    ) -> None:
        """
        Initialise le service de reparation.

        Args:
            file_system: Adaptateur filesystem (IFileSystem + ISymlinkManager)
            video_file_repo: Repository des fichiers video
            storage_dir: Dossier de stockage physique
            video_dir: Dossier des symlinks video
            trash_dir: Dossier pour les fichiers orphelins
        """
        self._file_system = file_system
        self._video_file_repo = video_file_repo
        self._storage_dir = storage_dir
        self._video_dir = video_dir
        self._trash_dir = trash_dir
        # Index des fichiers video: {chemin_normalise: [(Path, nom_normalise), ...]}
        self._file_index: list[tuple[Path, str]] = []
        self._index_built = False

    def _get_index_cache_path(self) -> Path:
        """Retourne le chemin du fichier cache de l'index."""
        cache_dir = Path.home() / ".cineorg"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "file_index.json"

    def _load_cached_index(self, max_age_hours: int = 24) -> bool:
        """
        Charge l'index depuis le cache s'il existe et n'est pas trop vieux.

        Args:
            max_age_hours: Age maximum du cache en heures

        Returns:
            True si l'index a ete charge depuis le cache
        """
        import time

        cache_path = self._get_index_cache_path()
        if not cache_path.exists():
            return False

        try:
            # Verifier l'age du cache
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age > max_age_hours * 3600:
                logger.debug(f"Cache d'index trop vieux ({cache_age/3600:.1f}h)")
                return False

            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Verifier que le storage_dir correspond
            if data.get("storage_dir") != str(self._storage_dir):
                logger.debug("Cache d'index pour un autre storage_dir")
                return False

            # Verifier la version du cache (version 2 requis pour clean_title)
            cache_version = data.get("version", 1)
            if cache_version < 2:
                logger.debug("Cache d'index version obsolete, reconstruction necessaire")
                return False

            # Charger l'index (version 2 avec clean_title)
            self._file_index = [
                (Path(item["path"]), item["normalized"], item.get("clean_title", ""))
                for item in data.get("files", [])
            ]
            self._index_built = True
            logger.debug(f"Index charge depuis le cache: {len(self._file_index)} fichiers")
            return True

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.debug(f"Erreur chargement cache d'index: {e}")
            return False

    def _save_index_to_cache(self) -> None:
        """Sauvegarde l'index dans le cache."""
        cache_path = self._get_index_cache_path()
        try:
            data = {
                "version": 2,  # Version du format de cache
                "storage_dir": str(self._storage_dir),
                "files": [
                    {"path": str(path), "normalized": norm, "clean_title": clean}
                    for path, norm, clean in self._file_index
                ],
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.debug(f"Index sauvegarde dans le cache: {cache_path}")
        except OSError as e:
            logger.warning(f"Impossible de sauvegarder le cache d'index: {e}")

    def build_file_index(
        self,
        progress_callback: Optional[callable] = None,
        force_rebuild: bool = False,
        max_cache_age_hours: int = 24,
    ) -> int:
        """
        Construit un index de tous les fichiers video dans storage.

        Utilise un cache persistant pour eviter de rescanner a chaque commande.
        Limite l'indexation aux repertoires Films et Series.

        Args:
            progress_callback: Fonction appelee avec (fichiers_indexes, message)
            force_rebuild: Force la reconstruction meme si le cache est valide
            max_cache_age_hours: Age maximum du cache en heures (defaut: 24h)

        Returns:
            Nombre de fichiers indexes
        """
        from src.adapters.file_system import VIDEO_EXTENSIONS

        if not self._storage_dir or not self._storage_dir.exists():
            return 0

        # Essayer de charger depuis le cache
        if not force_rebuild and self._load_cached_index(max_cache_age_hours):
            if progress_callback:
                progress_callback(len(self._file_index), f"Index charge (cache): {len(self._file_index)} fichiers")
            return len(self._file_index)

        self._file_index = []
        count = 0

        # Limiter aux repertoires de videos (Films et Series)
        media_dirs = []
        for subdir in ["Films", "Séries", "Series"]:
            media_path = self._storage_dir / subdir
            if media_path.exists():
                media_dirs.append(media_path)
                if progress_callback:
                    progress_callback(count, f"Scan: {media_path}")

        # Fallback: si aucun sous-repertoire Films/Series, scanner storage_dir
        if not media_dirs:
            media_dirs = [self._storage_dir]

        for media_dir in media_dirs:
            for candidate in media_dir.rglob("*"):
                try:
                    # Verifier symlink EN PREMIER
                    if candidate.is_symlink():
                        continue
                    if candidate.is_dir():
                        continue

                    # Verifier que c'est un fichier video
                    if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue

                    # Normaliser le nom pour comparaison rapide
                    normalized = self._normalize_filename(candidate.name)
                    # Extraire aussi le titre nettoye (sans termes techniques)
                    clean_title = self._extract_clean_title(candidate.name)
                    self._file_index.append((candidate, normalized, clean_title))
                    count += 1

                    if progress_callback and count % 500 == 0:
                        progress_callback(count, f"Indexation: {count} fichiers...")

                except (PermissionError, OSError):
                    continue

        self._index_built = True

        # Sauvegarder dans le cache
        self._save_index_to_cache()

        if progress_callback:
            progress_callback(count, f"Index construit: {count} fichiers")

        return count

    def _normalize_filename(self, name: str) -> str:
        """Normalise un nom de fichier pour comparaison."""
        stem = Path(name).stem.lower()
        for sep in [".", "_", "-"]:
            stem = stem.replace(sep, " ")
        return stem

    def _extract_clean_title(self, name: str) -> str:
        """
        Extrait le titre pur d'un nom de fichier via guessit.

        Args:
            name: Nom du fichier

        Returns:
            Titre nettoye (minuscules)
        """
        from guessit import guessit

        try:
            result = guessit(name)
            title = result.get("title", "")
            if title:
                return title.lower()
        except Exception:
            pass

        # Fallback: retourner le stem normalise
        return self._normalize_filename(name)

    def _extract_series_info(self, name: str) -> tuple[str, str | None, int | None, int | None]:
        """
        Extrait les informations structurees d'un nom de fichier de serie.

        Args:
            name: Nom du fichier

        Returns:
            Tuple (titre_normalise, saison, episode, annee)
        """
        import re

        stem = Path(name).stem.lower()

        # Remplacer les separateurs
        for sep in [".", "_", "-"]:
            stem = stem.replace(sep, " ")

        # Extraire saison/episode (S01E03, S01 E03, 1x03, etc.)
        season = None
        episode = None
        episode_match = re.search(r"\bs(\d{1,2})\s*e(\d{1,2})\b", stem)
        if episode_match:
            season = int(episode_match.group(1))
            episode = int(episode_match.group(2))
        else:
            # Format alternatif 1x03
            alt_match = re.search(r"\b(\d{1,2})x(\d{1,2})\b", stem)
            if alt_match:
                season = int(alt_match.group(1))
                episode = int(alt_match.group(2))

        # Extraire l'annee
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", stem)
        year = int(year_match.group(1)) if year_match else None

        # Extraire le titre (tout avant SxxExx ou l'annee)
        title = stem
        if episode_match:
            title = stem[: episode_match.start()].strip()
        elif year_match:
            title = stem[: year_match.start()].strip()

        # Nettoyer le titre des termes techniques
        tech_terms = [
            "french", "vostfr", "multi", "truefrench", "vff", "vf", "vo",
            "720p", "1080p", "2160p", "4k", "uhd",
            "x264", "x265", "hevc", "h264", "h265", "avc",
            "bluray", "bdrip", "webrip", "hdtv", "dvdrip", "web dl", "web",
            "dts", "ac3", "aac", "dolby", "atmos", "truehd",
            "internal", "final", "repack", "proper",
        ]
        for term in tech_terms:
            title = re.sub(rf"\b{term}\b", "", title, flags=re.IGNORECASE)

        # Nettoyer les espaces multiples
        title = " ".join(title.split())

        return title, season, episode, year

    def find_broken_symlinks(self) -> list[Path]:
        """
        Trouve tous les symlinks casses dans video/.

        Returns:
            Liste des chemins vers les symlinks casses
        """
        if not self._video_dir or not self._video_dir.exists():
            return []

        return self._file_system.find_broken_links(self._video_dir)

    def find_possible_targets(
        self, link: Path, min_score: float = 50.0
    ) -> list[tuple[Path, float]]:
        """
        Cherche des cibles possibles pour un symlink casse avec recherche floue.

        Strategie de recherche progressive:
        1. Meme genre (Films/Drame, Series/Animation, etc.)
        2. Meme type (Films ou Series)
        3. Toute la base de stockage

        Args:
            link: Chemin du symlink casse
            min_score: Score minimum de similarite (0-100)

        Returns:
            Liste de tuples (chemin, score) triee par score decroissant
        """
        if not self._storage_dir or not self._storage_dir.exists():
            return []

        # Detecter le type et genre depuis le chemin du symlink
        media_type, genre = self._detect_media_context(link)

        # Construire les chemins de recherche progressifs
        search_paths = []

        if media_type and genre:
            # 1. Meme genre
            genre_path = self._storage_dir / media_type / genre
            if genre_path.exists():
                search_paths.append(("genre", genre_path))

        if media_type:
            # 2. Meme type (Films ou Series)
            type_path = self._storage_dir / media_type
            if type_path.exists():
                search_paths.append(("type", type_path))

        # 3. Toute la base
        search_paths.append(("base", self._storage_dir))

        # Recherche progressive
        for scope, search_path in search_paths:
            candidates = self._search_in_directory(link, search_path, min_score)
            if candidates and candidates[0][1] >= 70:
                # Bon match trouve, on s'arrete
                return candidates

        # Si aucun bon match, retourner les resultats de la recherche complete
        # mais filtrer par type de media pour eviter de proposer des series pour des films
        return self._search_in_directory(
            link, self._storage_dir, min_score, media_type_filter=media_type
        )

    def _detect_media_context(self, link: Path) -> tuple[str | None, str | None]:
        """
        Detecte le type de media et le genre depuis le chemin du symlink.

        Args:
            link: Chemin du symlink

        Returns:
            Tuple (type, genre) ou (None, None) si non detecte
        """
        # Parcourir les parents du symlink pour detecter Films/Series et le genre
        parts = link.parts
        media_type = None
        genre = None

        for i, part in enumerate(parts):
            part_lower = part.lower()
            if part_lower == "films":
                media_type = "Films"
                # Le genre est le repertoire suivant (si existe)
                if i + 1 < len(parts) and not parts[i + 1].startswith(("A-", "H-", "R-")):
                    # C'est probablement un genre, pas une subdivision alphabetique
                    genre = parts[i + 1]
                elif i + 1 < len(parts):
                    # C'est une subdivision, on prend quand meme
                    genre = parts[i + 1]
                break
            elif part_lower in ("series", "séries"):
                media_type = "Séries"
                # Pour les series, structure peut etre differente
                if i + 1 < len(parts):
                    genre = parts[i + 1]
                break

        return media_type, genre

    def _search_in_directory(
        self, link: Path, search_dir: Path, min_score: float,
        media_type_filter: str | None = None
    ) -> list[tuple[Path, float]]:
        """
        Recherche des candidats dans un repertoire specifique.

        Utilise l'index pre-construit si disponible pour des performances
        optimales. Sinon, effectue une recherche directe (plus lente).

        Args:
            link: Chemin du symlink casse
            search_dir: Repertoire de recherche
            min_score: Score minimum
            media_type_filter: Filtrer par type ("Films" ou "Séries")

        Returns:
            Liste de tuples (chemin, score) triee par score decroissant
        """
        filename = link.name

        # Lire la cible originale du symlink pour comparaison
        try:
            original_target = link.readlink()
            original_name = original_target.name
        except OSError:
            original_name = filename

        # Detecter si le nom de la cible est "cryptique" (code release, pas de titre lisible)
        # Ex: "ninhd-ltrt-1080_HEVC_remux.mkv" vs "La pizzeria en révolte (1989).mkv"
        def is_cryptic_name(name: str) -> bool:
            """Detecte si un nom de fichier est cryptique (code release)."""
            import re
            stem = Path(name).stem.lower()

            # Un nom n'est pas cryptique s'il a une annee (avec ou sans parentheses)
            has_year = bool(re.search(r"\b(19\d{2}|20\d{2})\b", stem))
            if has_year:
                return False

            # Normaliser: remplacer les separateurs par des espaces
            for sep in [".", "_", "-"]:
                stem = stem.replace(sep, " ")

            # Supprimer les termes techniques et les groupes de release connus
            tech_terms = ["hevc", "x264", "x265", "h264", "h265", "remux", "1080p", "720p", "2160p",
                         "multi", "french", "vostfr", "bluray", "webrip", "web", "dts", "ac3",
                         "aac", "internal", "proper", "repack", "hdr", "10bit", "fraternity",
                         "extreme", "notag", "lost", "azaze", "cielos", "jiheff", "mhdgz",
                         "fhd", "hd", "sd", "uhd", "dvdrip", "bdrip", "tvrip", "eac3"]
            clean = stem
            for term in tech_terms:
                clean = re.sub(rf"\b{term}\b", "", clean, flags=re.IGNORECASE)

            # Supprimer les chiffres isoles
            clean = re.sub(r"\b\d+\b", "", clean)
            clean = " ".join(clean.split())  # Nettoyer espaces

            # Heuristique: un vrai mot a un bon ratio voyelles/consonnes et est prononçable
            vowels = set("aeiouyàâäéèêëïîôùûü")

            def is_word_like(word: str) -> bool:
                """Verifie si un mot ressemble a un vrai mot (pas un code)."""
                if len(word) < 3:
                    return False
                # Ratio de voyelles (les vrais mots ont generalement >25%)
                vowel_count = sum(1 for c in word if c in vowels)
                vowel_ratio = vowel_count / len(word)
                if vowel_ratio < 0.2:
                    return False
                # Verifier les consonnes consecutives (max 2-3 pour un vrai mot)
                consonant_streak = 0
                max_streak = 0
                for c in word:
                    if c not in vowels:
                        consonant_streak += 1
                        max_streak = max(max_streak, consonant_streak)
                    else:
                        consonant_streak = 0
                # Plus de 3 consonnes consecutives = probablement pas un vrai mot
                # (sauf exceptions comme "str", "scr", "thr" en debut de mot)
                if max_streak > 3:
                    return False
                return True

            # Filtrer les mots qui ressemblent a des vrais mots
            words = [w for w in clean.split() if len(w) >= 3 and w.isalpha() and is_word_like(w)]

            # Un titre normal a au moins 2 mots lisibles OU un mot long (> 6 lettres)
            has_long_word = any(len(w) >= 7 for w in words)
            has_multiple_words = len(words) >= 2

            return not (has_long_word or has_multiple_words)

        # Normaliser les noms de recherche
        norm_link = self._normalize_filename(filename)
        clean_link = self._extract_clean_title(filename)
        # N'utiliser le nom de la cible que s'il n'est pas cryptique
        use_target_name = not is_cryptic_name(original_name)
        norm_target = self._normalize_filename(original_name) if use_target_name else ""
        clean_target = self._extract_clean_title(original_name) if use_target_name else ""

        candidates: list[tuple[Path, float]] = []
        search_str = str(search_dir)

        # Utiliser l'index pre-construit si disponible
        if self._index_built:
            for candidate_path, candidate_norm, candidate_clean in self._file_index:
                # Filtrer par repertoire
                if not str(candidate_path).startswith(search_str):
                    continue

                # Filtrer par type de media (Films vs Series)
                if media_type_filter:
                    candidate_str = str(candidate_path).lower()
                    if media_type_filter.lower() == "films":
                        if "/séries/" in candidate_str or "/series/" in candidate_str:
                            continue
                    elif media_type_filter.lower() in ("séries", "series"):
                        if "/films/" in candidate_str:
                            continue

                # Calculer la similarite avec les titres nettoyes (priorite)
                # puis avec les noms normalises complets
                score_clean_link = self._calculate_similarity_fast(clean_link, candidate_clean)
                score_norm_link = self._calculate_similarity_fast(norm_link, candidate_norm)

                if clean_target:
                    score_clean_target = self._calculate_similarity_fast(clean_target, candidate_clean)
                    score_norm_target = self._calculate_similarity_fast(norm_target, candidate_norm)
                    # Prendre le meilleur score parmi les 4 comparaisons
                    score = max(score_clean_link, score_norm_link, score_clean_target, score_norm_target)
                else:
                    score = max(score_clean_link, score_norm_link)

                # Match exact = score maximum
                if candidate_path.name == filename or candidate_path.name == original_name:
                    score = 100.0

                if score >= min_score:
                    candidates.append((candidate_path, score))

        else:
            # Fallback: recherche directe (plus lente)
            from src.adapters.file_system import VIDEO_EXTENSIONS

            for candidate in search_dir.rglob("*"):
                try:
                    if candidate.is_symlink():
                        continue
                    if candidate.is_dir():
                        continue
                    if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue

                    score_link = self._calculate_title_similarity(filename, candidate.name)
                    # N'utiliser le nom de la cible que s'il n'est pas cryptique
                    if use_target_name:
                        score_target = self._calculate_title_similarity(original_name, candidate.name)
                        score = max(score_link, score_target)
                    else:
                        score = score_link

                    if candidate.name == filename or candidate.name == original_name:
                        score = 100.0

                    if score >= min_score:
                        candidates.append((candidate, score))

                except (PermissionError, OSError):
                    continue

        # Trier par score decroissant et limiter
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:15]

    def _calculate_similarity_fast(self, norm1: str, norm2: str) -> float:
        """
        Calcule rapidement la similarite entre deux noms deja normalises.

        Version optimisee qui assume que les noms sont deja normalises.
        Pour les series, compare le titre et l'episode separement.
        """
        from difflib import SequenceMatcher

        # Extraire les informations structurees
        title1, season1, episode1, year1 = self._extract_series_info(norm1)
        title2, season2, episode2, year2 = self._extract_series_info(norm2)

        # Similarite des titres
        if title1 and title2:
            title_ratio = SequenceMatcher(None, title1, title2).ratio()
        else:
            # Fallback sur la comparaison directe
            title_ratio = SequenceMatcher(None, norm1, norm2).ratio()

        # Pour les series: bonus/malus selon correspondance episode
        if season1 is not None and episode1 is not None:
            # C'est une serie
            if season2 == season1 and episode2 == episode1:
                # Meme episode: gros bonus
                return min(100.0, title_ratio * 100 + 30)
            elif season2 == season1 and episode2 is not None:
                # Meme saison mais episode different: malus
                return max(0.0, title_ratio * 100 - 20)
            elif episode2 is not None:
                # Saison differente: malus important
                return max(0.0, title_ratio * 100 - 30)

        # Pour les films ou si pas d'info episode: comparaison simple
        score = title_ratio * 100

        # Bonus/malus pour l'annee
        if year1 and year2:
            if year1 == year2:
                score = min(100.0, score + 10)
            elif abs(year1 - year2) > 2:
                score = max(0.0, score - 10)

        return score

    def _calculate_title_similarity(self, name1: str, name2: str) -> float:
        """
        Calcule la similarite entre deux noms de fichiers video.

        Extrait les titres et annees, puis compare avec SequenceMatcher.

        Args:
            name1: Premier nom de fichier
            name2: Deuxieme nom de fichier

        Returns:
            Score de similarite (0-100)
        """
        import re
        from difflib import SequenceMatcher

        def normalize_and_extract(name: str) -> tuple[str, int | None]:
            """Normalise un nom et extrait titre + annee."""
            # Supprimer l'extension
            stem = Path(name).stem.lower()

            # Remplacer les separateurs
            for sep in [".", "_", "-"]:
                stem = stem.replace(sep, " ")

            # Chercher une annee
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", stem)
            year = int(year_match.group(1)) if year_match else None

            # Extraire le titre (avant l'annee ou infos techniques)
            title = stem
            if year_match:
                title = stem[: year_match.start()]

            # Supprimer les infos techniques
            tech_patterns = [
                r"\b(french|vostfr|multi|truefrench|vff|vf|vo|eng)\b",
                r"\b(720p|1080p|2160p|4k|uhd)\b",
                r"\b(x264|x265|hevc|h264|h265|avc)\b",
                r"\b(bluray|bdrip|webrip|hdtv|dvdrip|web)\b",
                r"\b(dts|ac3|aac|dolby|atmos|truehd|dd|ddp)\b",
                r"\b(remux|proper|repack)\b",
            ]
            for pattern in tech_patterns:
                title = re.sub(pattern, "", title, flags=re.IGNORECASE)

            # Nettoyer les espaces
            while "  " in title:
                title = title.replace("  ", " ")

            return title.strip(), year

        title1, year1 = normalize_and_extract(name1)
        title2, year2 = normalize_and_extract(name2)

        # Similarite des titres
        title_ratio = SequenceMatcher(None, title1, title2).ratio()

        # Bonus/malus pour l'annee
        year_bonus = 0.0
        if year1 and year2:
            if year1 == year2:
                year_bonus = 0.15  # +15% si meme annee
            elif abs(year1 - year2) <= 1:
                year_bonus = 0.05  # +5% si annee proche
            else:
                year_bonus = -0.15  # -15% si annee differente

        score = (title_ratio + year_bonus) * 100
        return max(0.0, min(100.0, score))

    def repair_symlink(self, link: Path, new_target: Path) -> bool:
        """
        Repare un symlink en le recreant avec une nouvelle cible.

        Args:
            link: Chemin du symlink casse
            new_target: Nouvelle cible pour le symlink

        Returns:
            True si reparation reussie, False sinon
        """
        try:
            # Supprimer l'ancien lien
            if link.is_symlink():
                link.unlink()

            # Creer le nouveau lien
            success = self._file_system.create_symlink(new_target, link)

            if success:
                logger.info(f"Symlink repare: {link} -> {new_target}")
            return success

        except OSError as e:
            logger.error(f"Erreur lors de la reparation du symlink {link}: {e}")
            return False

    def move_to_orphans(self, link: Path) -> Optional[Path]:
        """
        Deplace un symlink orphelin vers trash/orphans.

        Args:
            link: Chemin du symlink a deplacer

        Returns:
            Nouveau chemin dans trash/orphans, ou None si echec
        """
        if not self._trash_dir:
            logger.warning("trash_dir non configure, impossible de deplacer le lien")
            return None

        # Creer le dossier orphans si necessaire
        orphans_dir = self._trash_dir / "orphans"
        orphans_dir.mkdir(parents=True, exist_ok=True)

        # Nom du fichier de destination
        dest_name = link.name
        dest_path = orphans_dir / dest_name

        # Gerer les conflits de nom avec timestamp
        if dest_path.exists() or dest_path.is_symlink():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_name = f"{link.stem}_{timestamp}{link.suffix}"
            dest_path = orphans_dir / dest_name

        try:
            # Deplacer le symlink (pas son contenu)
            link.rename(dest_path)
            logger.info(f"Symlink deplace vers orphans: {link} -> {dest_path}")
            return dest_path

        except OSError as e:
            logger.error(f"Erreur lors du deplacement vers orphans {link}: {e}")
            return None

    def save_log(
        self, actions: list[RepairAction], log_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Sauvegarde le journal des actions de reparation.

        Args:
            actions: Liste des actions effectuees
            log_dir: Dossier pour le fichier log (defaut: trash_dir)

        Returns:
            Chemin vers le fichier log cree, ou None si echec
        """
        if not actions:
            return None

        # Determiner le dossier de log avec fallback
        target_dir = log_dir or self._trash_dir

        # Liste des dossiers de fallback si le dossier principal n'est pas accessible
        fallback_dirs = [
            target_dir,
            self._storage_dir / "logs" if self._storage_dir else None,
            Path.home() / ".cineorg" / "logs",
            Path.cwd() / "logs",
        ]

        # Trouver un dossier accessible
        for candidate_dir in fallback_dirs:
            if candidate_dir is None:
                continue
            try:
                candidate_dir.mkdir(parents=True, exist_ok=True)
                target_dir = candidate_dir
                break
            except PermissionError:
                logger.debug(f"Dossier de log non accessible: {candidate_dir}")
                continue
            except OSError as e:
                logger.debug(f"Erreur creation dossier de log {candidate_dir}: {e}")
                continue
        else:
            logger.warning("Aucun dossier accessible pour sauvegarder le log")
            return None

        # Nom du fichier avec date
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"repair-{date_str}.log"
        log_path = target_dir / log_filename

        # Ecrire le log en JSON
        try:
            log_data = {
                "date": date_str,
                "actions_count": len(actions),
                "summary": {
                    "repaired": sum(1 for a in actions if a.action == RepairActionType.REPAIRED),
                    "orphaned": sum(1 for a in actions if a.action == RepairActionType.ORPHANED),
                    "skipped": sum(1 for a in actions if a.action == RepairActionType.SKIPPED),
                },
                "actions": [a.to_dict() for a in actions],
            }

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Log de reparation sauvegarde: {log_path}")
            return log_path

        except OSError as e:
            logger.error(f"Erreur lors de l'ecriture du log: {e}")
            return None
