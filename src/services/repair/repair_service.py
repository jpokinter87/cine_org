"""
Service de reparation des symlinks casses.

Orchestre la recherche de cibles de reparation et les operations de
reparation/deplacement des symlinks casses dans la videotheque.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src.services.integrity import RepairAction, RepairActionType

from .file_indexer import FileIndexer
from .filename_analyzer import extract_clean_title, normalize_filename
from .similarity_matcher import calculate_similarity_fast, calculate_title_similarity


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
        # Deleguer l'indexation au FileIndexer
        self._indexer = FileIndexer(storage_dir)

    # --- Proprietes de compatibilite pour l'acces a l'index ---

    @property
    def _file_index(self) -> list[tuple[Path, str, str]]:
        return self._indexer.file_index

    @_file_index.setter
    def _file_index(self, value: list) -> None:
        self._indexer._file_index = value

    @property
    def _index_built(self) -> bool:
        return self._indexer.index_built

    @_index_built.setter
    def _index_built(self, value: bool) -> None:
        self._indexer._index_built = value

    # --- Delegation des methodes d'analyse de noms ---

    @staticmethod
    def _normalize_filename(name: str) -> str:
        """Normalise un nom de fichier pour comparaison."""
        return normalize_filename(name)

    @staticmethod
    def _extract_clean_title(name: str) -> str:
        """Extrait le titre pur d'un nom de fichier via guessit."""
        return extract_clean_title(name)

    @staticmethod
    def _extract_series_info(name: str) -> tuple[str, str | None, int | None, int | None]:
        """Extrait les informations structurees d'un nom de fichier de serie."""
        from .filename_analyzer import extract_series_info
        return extract_series_info(name)

    # --- Delegation des methodes de similarite ---

    @staticmethod
    def _calculate_similarity_fast(norm1: str, norm2: str) -> float:
        """Calcule rapidement la similarite entre deux noms normalises."""
        return calculate_similarity_fast(norm1, norm2)

    @staticmethod
    def _calculate_title_similarity(name1: str, name2: str) -> float:
        """Calcule la similarite entre deux noms de fichiers video."""
        return calculate_title_similarity(name1, name2)

    # --- Delegation de l'indexation ---

    def _get_index_cache_path(self) -> Path:
        """Retourne le chemin du fichier cache de l'index."""
        return self._indexer._get_index_cache_path()

    def _load_cached_index(self, max_age_hours: int = 24, scan_all: bool = False) -> bool:
        """Charge l'index depuis le cache."""
        return self._indexer._load_cached_index(max_age_hours, scan_all)

    def _save_index_to_cache(self, scan_all: bool = False) -> None:
        """Sauvegarde l'index dans le cache."""
        self._indexer._save_index_to_cache(scan_all)

    def build_file_index(
        self,
        progress_callback: Optional[callable] = None,
        force_rebuild: bool = False,
        max_cache_age_hours: int = 24,
        scan_all: bool = False,
    ) -> int:
        """
        Construit un index de tous les fichiers video dans storage.

        Args:
            progress_callback: Fonction appelee avec (fichiers_indexes, message)
            force_rebuild: Force la reconstruction meme si le cache est valide
            max_cache_age_hours: Age maximum du cache en heures (defaut: 24h)
            scan_all: Scanner tous les sous-repertoires (pas seulement Films/Series)

        Returns:
            Nombre de fichiers indexes
        """
        return self._indexer.build_file_index(
            progress_callback=progress_callback,
            force_rebuild=force_rebuild,
            max_cache_age_hours=max_cache_age_hours,
            scan_all=scan_all,
        )

    # --- Recherche de symlinks casses ---

    def find_broken_symlinks(self) -> list[Path]:
        """
        Trouve tous les symlinks casses dans video/.

        Returns:
            Liste des chemins vers les symlinks casses
        """
        if not self._video_dir or not self._video_dir.exists():
            return []

        return self._file_system.find_broken_links(self._video_dir)

    # --- Recherche de cibles ---

    def _find_regroup_candidates(
        self, link: Path, min_score: float = 0.0,
        alternative_names: list[str] | None = None,
    ) -> list[tuple[Path, float]]:
        """
        Recherche ciblee pour les symlinks brises par le bug regroup.

        Le bug regroup ajoutait un sous-repertoire prefixe dans le chemin NAS
        de la cible sans y deplacer les fichiers. Les fichiers sont restes
        dans le repertoire parent ou le grand-parent.

        Args:
            link: Chemin du symlink casse
            min_score: Score minimum (defaut 0 car l'espace de recherche est restreint)
            alternative_names: Noms alternatifs pour le scoring

        Returns:
            Liste de tuples (chemin, score) triee par score decroissant
        """
        from src.adapters.file_system import VIDEO_EXTENSIONS

        try:
            original_target = link.readlink()
        except OSError:
            return []

        target_parent = original_target.parent
        target_grandparent = target_parent.parent

        # Collecter les repertoires a scanner (parent et/ou grand-parent)
        search_dirs: list[Path] = []
        if target_parent.exists():
            search_dirs.append(target_parent)
        if target_grandparent.exists() and target_grandparent != target_parent:
            search_dirs.append(target_grandparent)

        if not search_dirs:
            return []

        # Preparer les noms de comparaison (symlink + cible originale + alternatifs)
        link_name = link.name
        target_name = original_target.name
        clean_link = extract_clean_title(link_name)
        clean_target = extract_clean_title(target_name) if target_name != link_name else ""

        # Preparer les titres alternatifs (ex: titre original TMDB)
        clean_alternatives: list[str] = []
        if alternative_names:
            for alt_name in alternative_names:
                clean_alt = extract_clean_title(alt_name)
                if clean_alt and clean_alt != clean_link:
                    clean_alternatives.append(clean_alt)

        # Lister les fichiers video dans les repertoires de recherche
        candidates: list[tuple[Path, float]] = []
        seen: set[str] = set()

        for search_dir in search_dirs:
            try:
                for f in search_dir.iterdir():
                    try:
                        if f.is_symlink() or f.is_dir():
                            continue
                        if f.suffix.lower() not in VIDEO_EXTENSIONS:
                            continue

                        real = str(f)
                        if real in seen:
                            continue
                        seen.add(real)

                        # Match exact sur le nom
                        if f.name == link_name or f.name == target_name:
                            candidates.append((f, 100.0))
                            continue

                        # Calculer avec titres complets
                        score_link = calculate_title_similarity(link_name, f.name)
                        # Calculer avec titres nettoyés (guessit)
                        clean_candidate = extract_clean_title(f.name)
                        score_clean = calculate_similarity_fast(clean_link, clean_candidate)

                        scores = [score_link, score_clean]

                        # Comparer aussi avec le nom de la cible originale
                        if clean_target:
                            score_target = calculate_title_similarity(target_name, f.name)
                            score_target_clean = calculate_similarity_fast(
                                clean_target, clean_candidate
                            )
                            scores.extend([score_target, score_target_clean])

                        # Comparer avec les titres alternatifs (ex: titre original TMDB)
                        for clean_alt in clean_alternatives:
                            score_alt = calculate_similarity_fast(
                                clean_alt, clean_candidate
                            )
                            scores.append(score_alt)

                        score = max(scores)

                        if score >= min_score:
                            candidates.append((f, score))
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                continue

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def find_possible_targets(
        self, link: Path, min_score: float = 50.0,
        alternative_names: list[str] | None = None,
    ) -> list[tuple[Path, float]]:
        """
        Cherche des cibles possibles pour un symlink casse avec recherche floue.

        Strategie de recherche progressive:
        1. Recherche ciblee regroup (repertoire NAS parent/grand-parent)
        2. Recherche floue dans toute la base de stockage

        Args:
            link: Chemin du symlink casse
            min_score: Score minimum de similarite (0-100)
            alternative_names: Noms alternatifs pour le scoring

        Returns:
            Liste de tuples (chemin, score) triee par score decroissant
        """
        if not self._storage_dir or not self._storage_dir.exists():
            return []

        # Phase 1 : recherche ciblee regroup (peu de candidats, rapide)
        regroup_candidates = self._find_regroup_candidates(
            link, alternative_names=alternative_names
        )

        # Utiliser les candidats regroup seulement si le meilleur score est bon
        if regroup_candidates and regroup_candidates[0][1] >= 60:
            return regroup_candidates

        # Phase 2 : recherche floue dans toute la base
        media_type, genre = self._detect_media_context(link)
        index_candidates = self._search_in_directory(
            link, self._storage_dir, min_score, media_type_filter=media_type
        )

        # Fusionner : si les deux phases ont des resultats, combiner sans doublons
        if regroup_candidates and index_candidates:
            seen = {str(p) for p, _ in index_candidates}
            merged = list(index_candidates)
            for path, score in regroup_candidates:
                if str(path) not in seen:
                    merged.append((path, score))
            merged.sort(key=lambda x: x[1], reverse=True)
            return merged[:15]

        return index_candidates or regroup_candidates

    def _detect_media_context(self, link: Path) -> tuple[str | None, str | None]:
        """
        Detecte le type de media et le genre depuis le chemin du symlink.

        Args:
            link: Chemin du symlink

        Returns:
            Tuple (type, genre) ou (None, None) si non detecte
        """
        parts = link.parts
        media_type = None
        genre = None

        for i, part in enumerate(parts):
            part_lower = part.lower()
            if part_lower == "films":
                media_type = "Films"
                if i + 1 < len(parts) and not parts[i + 1].startswith(("A-", "H-", "R-")):
                    genre = parts[i + 1]
                elif i + 1 < len(parts):
                    genre = parts[i + 1]
                break
            elif part_lower in ("series", "séries"):
                media_type = "Séries"
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
        def is_cryptic_name(name: str) -> bool:
            """Detecte si un nom de fichier est cryptique (code release)."""
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
                vowel_count = sum(1 for c in word if c in vowels)
                vowel_ratio = vowel_count / len(word)
                if vowel_ratio < 0.2:
                    return False
                consonant_streak = 0
                max_streak = 0
                for c in word:
                    if c not in vowels:
                        consonant_streak += 1
                        max_streak = max(max_streak, consonant_streak)
                    else:
                        consonant_streak = 0
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
        norm_link = normalize_filename(filename)
        clean_link = extract_clean_title(filename)
        # N'utiliser le nom de la cible que s'il n'est pas cryptique
        use_target_name = not is_cryptic_name(original_name)
        norm_target = normalize_filename(original_name) if use_target_name else ""
        clean_target = extract_clean_title(original_name) if use_target_name else ""

        candidates: list[tuple[Path, float]] = []
        search_str = str(search_dir)

        # Utiliser l'index pre-construit si disponible
        if self._indexer.index_built:
            for candidate_path, candidate_norm, candidate_clean in self._indexer.file_index:
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
                score_clean_link = calculate_similarity_fast(clean_link, candidate_clean)
                score_norm_link = calculate_similarity_fast(norm_link, candidate_norm)

                if clean_target:
                    score_clean_target = calculate_similarity_fast(clean_target, candidate_clean)
                    score_norm_target = calculate_similarity_fast(norm_target, candidate_norm)
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

                    score_link = calculate_title_similarity(filename, candidate.name)
                    # N'utiliser le nom de la cible que s'il n'est pas cryptique
                    if use_target_name:
                        score_target = calculate_title_similarity(original_name, candidate.name)
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

    # --- Operations de reparation ---

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
