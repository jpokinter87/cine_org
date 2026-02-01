"""
Service de reparation des symlinks brises.

Detecte les symlinks dont la cible n'existe plus et recherche des fichiers
similaires dans le repertoire de stockage pour proposer des reparations.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Callable, Generator, Optional

from src.adapters.file_system import VIDEO_EXTENSIONS


class RepairDecision(Enum):
    """Decision prise pour un symlink brise."""

    REPAIRED = "repaired"  # Symlink repare avec succes
    NO_MATCH = "no_match"  # Aucun candidat trouve
    SKIPPED = "skipped"  # Symlink ignore (deja valide ou non-video)
    ERROR = "error"  # Erreur lors du traitement


@dataclass
class RepairCandidate:
    """
    Candidat pour la reparation d'un symlink.

    Attributs:
        path: Chemin du fichier candidat
        score: Score de similarite (0-100)
        size_bytes: Taille du fichier en octets
        match_reason: Raison du match (nom similaire, meme taille, etc.)
    """

    path: Path
    score: float
    size_bytes: int
    match_reason: str


@dataclass
class RepairResult:
    """
    Resultat de la reparation d'un symlink.

    Attributs:
        symlink_path: Chemin du symlink traite
        original_target: Cible originale du symlink (brisee)
        decision: Decision prise
        new_target: Nouvelle cible si repare
        candidates: Liste des candidats trouves
        error_message: Message d'erreur si erreur
    """

    symlink_path: Path
    original_target: Path
    decision: RepairDecision
    new_target: Optional[Path] = None
    candidates: list[RepairCandidate] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []


class SymlinkRepairService:
    """
    Service de reparation des symlinks brises.

    Scanne un repertoire de symlinks, detecte ceux qui sont brises,
    et recherche des fichiers similaires pour proposer des reparations.
    """

    def __init__(
        self,
        storage_dir: Path,
        min_score: float = 60.0,
        dry_run: bool = False,
    ) -> None:
        """
        Initialise le service de reparation.

        Args:
            storage_dir: Repertoire de stockage ou chercher les fichiers
            min_score: Score minimum pour considerer un candidat (0-100)
            dry_run: Si True, ne pas modifier les symlinks
        """
        self._storage_dir = storage_dir
        self._min_score = min_score
        self._dry_run = dry_run
        self._file_index: dict[str, list[Path]] = {}
        self._indexed = False

    def _build_file_index(self) -> None:
        """
        Construit un index des fichiers video dans le repertoire de stockage.

        L'index associe les noms de fichiers normalises a leurs chemins.
        """
        if self._indexed:
            return

        self._file_index = {}

        for file_path in self._storage_dir.rglob("*"):
            if file_path.is_file() and not file_path.is_symlink():
                if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                    # Indexer par nom normalise
                    normalized = self._normalize_filename(file_path.name)
                    if normalized not in self._file_index:
                        self._file_index[normalized] = []
                    self._file_index[normalized].append(file_path)

        self._indexed = True

    def _normalize_filename(self, filename: str) -> str:
        """
        Normalise un nom de fichier pour la comparaison.

        Supprime l'extension, met en minuscules, remplace les separateurs.
        """
        # Supprimer l'extension
        name = Path(filename).stem.lower()

        # Remplacer les separateurs courants par des espaces
        for sep in [".", "_", "-"]:
            name = name.replace(sep, " ")

        # Supprimer les espaces multiples
        while "  " in name:
            name = name.replace("  ", " ")

        return name.strip()

    def _extract_title_parts(self, filename: str) -> tuple[str, Optional[int]]:
        """
        Extrait le titre et l'annee d'un nom de fichier.

        Args:
            filename: Nom du fichier

        Returns:
            Tuple (titre normalise, annee ou None)
        """
        import re

        normalized = self._normalize_filename(filename)

        # Chercher une annee (4 chiffres entre 1900 et 2099)
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", normalized)
        year = int(year_match.group(1)) if year_match else None

        # Extraire le titre (tout avant l'annee ou les infos techniques)
        title = normalized
        if year_match:
            title = normalized[: year_match.start()].strip()

        # Supprimer les infos techniques courantes
        tech_patterns = [
            r"\b(french|vostfr|multi|truefrench|vff|vf|vo)\b",
            r"\b(720p|1080p|2160p|4k|uhd)\b",
            r"\b(x264|x265|hevc|h264|h265|avc)\b",
            r"\b(bluray|bdrip|webrip|hdtv|dvdrip|web dl|web)\b",
            r"\b(dts|ac3|aac|dolby|atmos|truehd)\b",
        ]
        for pattern in tech_patterns:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE)

        # Nettoyer
        while "  " in title:
            title = title.replace("  ", " ")

        return title.strip(), year

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """
        Calcule la similarite entre deux noms de fichiers.

        Args:
            name1: Premier nom de fichier
            name2: Deuxieme nom de fichier

        Returns:
            Score de similarite (0-100)
        """
        # Extraire titre et annee
        title1, year1 = self._extract_title_parts(name1)
        title2, year2 = self._extract_title_parts(name2)

        # Similarite des titres
        title_ratio = SequenceMatcher(None, title1, title2).ratio()

        # Bonus/malus pour l'annee
        year_bonus = 0.0
        if year1 and year2:
            if year1 == year2:
                year_bonus = 0.1  # +10% si meme annee
            elif abs(year1 - year2) <= 1:
                year_bonus = 0.05  # +5% si annee proche
            else:
                year_bonus = -0.1  # -10% si annee differente

        # Score final
        score = (title_ratio + year_bonus) * 100
        return max(0.0, min(100.0, score))

    def find_candidates(
        self, broken_target: Path, symlink_name: str
    ) -> list[RepairCandidate]:
        """
        Recherche des candidats pour remplacer une cible brisee.

        Args:
            broken_target: Chemin de la cible brisee
            symlink_name: Nom du symlink (pour la comparaison)

        Returns:
            Liste des candidats tries par score decroissant
        """
        self._build_file_index()

        candidates = []
        seen_paths = set()

        # Nom de la cible originale
        target_name = broken_target.name

        # Parcourir tous les fichiers indexes
        for normalized_name, paths in self._file_index.items():
            for file_path in paths:
                if file_path in seen_paths:
                    continue

                # Calculer la similarite avec le nom de la cible
                score_target = self._calculate_similarity(target_name, file_path.name)

                # Calculer aussi la similarite avec le nom du symlink
                score_symlink = self._calculate_similarity(symlink_name, file_path.name)

                # Prendre le meilleur score
                score = max(score_target, score_symlink)

                if score >= self._min_score:
                    try:
                        size = file_path.stat().st_size
                    except OSError:
                        size = 0

                    reason = []
                    if score_target >= self._min_score:
                        reason.append("nom cible similaire")
                    if score_symlink >= self._min_score:
                        reason.append("nom symlink similaire")

                    candidates.append(
                        RepairCandidate(
                            path=file_path,
                            score=score,
                            size_bytes=size,
                            match_reason=", ".join(reason),
                        )
                    )
                    seen_paths.add(file_path)

        # Trier par score decroissant
        candidates.sort(key=lambda c: c.score, reverse=True)

        return candidates[:10]  # Limiter a 10 candidats

    def scan_broken_symlinks(
        self, video_dir: Path
    ) -> Generator[RepairResult, None, None]:
        """
        Scanne un repertoire et detecte les symlinks brises.

        Args:
            video_dir: Repertoire a scanner

        Yields:
            RepairResult pour chaque symlink brise trouve
        """
        for symlink_path in video_dir.rglob("*"):
            # Ignorer les repertoires
            if symlink_path.is_dir():
                continue

            # Ne traiter que les symlinks
            if not symlink_path.is_symlink():
                continue

            # Verifier que c'est un fichier video
            if symlink_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            # Lire la cible du symlink
            try:
                target = Path(symlink_path).resolve()
            except OSError as e:
                yield RepairResult(
                    symlink_path=symlink_path,
                    original_target=Path(""),
                    decision=RepairDecision.ERROR,
                    error_message=f"Impossible de lire le symlink: {e}",
                )
                continue

            # Verifier si la cible existe
            if target.exists():
                # Symlink valide, ignorer
                continue

            # Symlink brise - chercher des candidats
            candidates = self.find_candidates(target, symlink_path.name)

            if not candidates:
                yield RepairResult(
                    symlink_path=symlink_path,
                    original_target=target,
                    decision=RepairDecision.NO_MATCH,
                    candidates=[],
                )
            else:
                yield RepairResult(
                    symlink_path=symlink_path,
                    original_target=target,
                    decision=RepairDecision.NO_MATCH,  # Sera change si repare
                    candidates=candidates,
                )

    def repair_symlink(
        self, symlink_path: Path, new_target: Path
    ) -> RepairResult:
        """
        Repare un symlink en changeant sa cible.

        Args:
            symlink_path: Chemin du symlink a reparer
            new_target: Nouvelle cible du symlink

        Returns:
            RepairResult avec le resultat de l'operation
        """
        try:
            # Lire l'ancienne cible
            try:
                original_target = Path(symlink_path).resolve()
            except OSError:
                original_target = Path(str(symlink_path.readlink()))

            if self._dry_run:
                return RepairResult(
                    symlink_path=symlink_path,
                    original_target=original_target,
                    decision=RepairDecision.REPAIRED,
                    new_target=new_target,
                )

            # Supprimer l'ancien symlink et creer le nouveau
            symlink_path.unlink()
            symlink_path.symlink_to(new_target)

            return RepairResult(
                symlink_path=symlink_path,
                original_target=original_target,
                decision=RepairDecision.REPAIRED,
                new_target=new_target,
            )

        except Exception as e:
            return RepairResult(
                symlink_path=symlink_path,
                original_target=Path(""),
                decision=RepairDecision.ERROR,
                error_message=str(e),
            )
