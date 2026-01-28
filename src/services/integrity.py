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

    def find_broken_symlinks(self) -> list[Path]:
        """
        Trouve tous les symlinks casses dans video/.

        Returns:
            Liste des chemins vers les symlinks casses
        """
        if not self._video_dir or not self._video_dir.exists():
            return []

        return self._file_system.find_broken_links(self._video_dir)

    def find_possible_targets(self, link: Path) -> list[Path]:
        """
        Cherche des cibles possibles pour un symlink casse.

        Recherche des fichiers avec le meme nom (ou nom similaire)
        dans le dossier storage.

        Args:
            link: Chemin du symlink casse

        Returns:
            Liste des cibles possibles, triees par pertinence
        """
        if not self._storage_dir or not self._storage_dir.exists():
            return []

        # Extraire le nom du fichier attendu
        filename = link.name
        filename_stem = link.stem

        possible_targets = []

        # Chercher dans storage avec le meme nom exact
        for candidate in self._storage_dir.rglob("*"):
            if candidate.is_dir():
                continue
            if candidate.is_symlink():
                continue

            # Match exact
            if candidate.name == filename:
                possible_targets.insert(0, candidate)  # Priorite haute
            # Match partiel (meme nom sans extension)
            elif candidate.stem == filename_stem:
                possible_targets.append(candidate)
            # Match par contenu du nom
            elif filename_stem.lower() in candidate.stem.lower():
                possible_targets.append(candidate)

        return possible_targets

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

        # Determiner le dossier de log
        target_dir = log_dir or self._trash_dir
        if not target_dir:
            logger.warning("Aucun dossier configure pour le log")
            return None

        target_dir.mkdir(parents=True, exist_ok=True)

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
