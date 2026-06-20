"""
Routes de transfert des fichiers validés.

Affiche le résumé batch des transferts prévus (arborescence),
permet l'exécution du transfert avec progression SSE,
et gère la résolution interactive des conflits.
"""

import asyncio
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse

from loguru import logger

from src.services.sandbox_service import REPLACED_SUBDIR
from ..deps import templates

router = APIRouter(prefix="/transfer")


# ═══════════════════════════════════════
# Structures de données
# ═══════════════════════════════════════


class BatchPrepareProgress:
    """État de progression partagé pour la préparation du batch."""

    def __init__(self) -> None:
        self.current: int = 0
        self.total: int = 0
        self.filename: str = ""
        self.message: str = "Initialisation…"
        self.complete: bool = False
        self.error: Optional[str] = None


class TransferProgress:
    """État de progression partagé entre le transfert et le SSE."""

    def __init__(self) -> None:
        self.current: int = 0
        self.total: int = 0
        self.filename: str = ""
        self.message: str = "Initialisation…"
        self.complete: bool = False
        self.error: Optional[str] = None

        # Conflit en attente de résolution
        self.conflict_pending: bool = False
        self.conflict_data: Optional[dict] = None
        self.conflict_choice: Optional[str] = None
        self.conflict_event: asyncio.Event = asyncio.Event()

        # Mode simulation
        self.dry_run: bool = False

        # Compteurs finaux
        self.transferred: int = 0
        self.duplicates_ignored: int = 0
        self.conflicts_resolved: int = 0
        self.errors: int = 0

        # Détails par fichier
        self.transferred_files: list[str] = []
        self.transferred_details: list[dict] = []  # {name, storage, symlink}
        self.duplicate_files: list[str] = []
        self.error_files: list[str] = []


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets en chaîne lisible."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} Mo"
    return f"{size_bytes / 1024:.0f} Ko"


def _get_sandbox_dir(settings) -> Path:
    """Retourne le répertoire sandbox pour les anciennes versions remplacées."""
    sandbox = getattr(settings, "sandbox_dir", None)
    if sandbox:
        return Path(sandbox)
    # Fallback : .sandbox dans la zone de stockage
    storage = getattr(settings, "storage_dir", None)
    if storage:
        return Path(storage) / ".sandbox"
    return Path("/tmp/cineorg_sandbox")


def _reject_source_to_sandbox(container, settings, source: Path) -> None:
    """Déplace un nouveau fichier rejeté (« Garder l'ancien ») vers le sandbox.

    Sort le fichier de downloads/ pour qu'il ne soit plus re-détecté aux
    traitements suivants. Échec → log, on ne bloque pas le transfert.
    """
    try:
        sandbox_svc = container.sandbox_service(
            sandbox_dir=settings.resolved_sandbox_dir,
            storage_dir=settings.storage_dir,
            downloads_dir=settings.downloads_dir,
        )
        sandbox_svc.sandbox_rejected([source])
    except Exception as e:
        logger.warning("Échec sandbox du rejet {}: {}", source, e)


def _resolve_storage_path(existing_dir: Path, storage_dir: Path) -> Path | None:
    """
    Trouve le vrai chemin storage en suivant les symlinks dans existing_dir.

    existing_dir est dans video_dir et contient des symlinks vers storage.
    On suit un symlink pour retrouver le répertoire storage réel,
    ce qui évite les problèmes de casse ou de noms différents.
    """
    # Chercher un symlink dans le dossier (récursivement pour les séries)
    try:
        for item in existing_dir.rglob("*"):
            if item.is_symlink():
                target = item.resolve()
                if target.exists():
                    # Remonter jusqu'au dossier correspondant à existing_dir
                    # Compter la profondeur relative du symlink par rapport à existing_dir
                    rel_depth = len(item.relative_to(existing_dir).parts) - 1
                    storage_path = target.parent
                    for _ in range(rel_depth):
                        storage_path = storage_path.parent
                    # Vérifier que c'est bien dans storage_dir
                    try:
                        storage_path.relative_to(storage_dir)
                    except ValueError:
                        continue
                    # Garde-fou : vérifier que ce n'est pas un répertoire de
                    # subdivision (contenant plusieurs séries/films). Un répertoire
                    # de contenu valide contient des fichiers vidéo ou des dossiers
                    # "Saison", pas d'autres répertoires de séries.
                    if _is_subdivision_path(storage_path):
                        logger.warning(
                            "Resolve storage: {} résolu vers subdivision {}, ignoré",
                            existing_dir,
                            storage_path,
                        )
                        continue
                    return storage_path
    except (PermissionError, OSError) as e:
        logger.warning("Erreur parcours symlinks dans %s: %s", existing_dir, e)

    return None


def _is_subdivision_path(path: Path) -> bool:
    """Vérifie si un chemin est un répertoire de subdivision (pas de contenu).

    Un répertoire de subdivision contient d'autres répertoires de séries/films.
    Un répertoire de contenu contient des fichiers vidéo ou des dossiers 'Saison'.
    """
    if not path.is_dir():
        return False

    try:
        subdirs = [d for d in path.iterdir() if d.is_dir()]
    except PermissionError:
        return False

    # S'il contient un dossier "Saison", c'est un répertoire de série → pas subdivision
    for d in subdirs:
        if d.name.lower().startswith("saison"):
            return False

    # S'il contient des fichiers vidéo directement, c'est du contenu
    from ...utils.constants import VIDEO_EXTENSIONS

    for item in path.iterdir():
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
            return False

    # S'il contient plusieurs sous-répertoires qui eux-mêmes ont du contenu,
    # c'est une subdivision
    content_dirs = 0
    for d in subdirs:
        # Vérifier si le sous-dossier contient du contenu (fichiers ou Saison)
        try:
            has_content = any(
                f.is_file() or f.name.lower().startswith("saison") for f in d.iterdir()
            )
            if has_content:
                content_dirs += 1
            if content_dirs >= 2:
                return True
        except PermissionError:
            continue

    return False


def _sandbox_existing(
    existing_dir: Path,
    sandbox_dir: Path,
    storage_dir: Path,
    video_dir: Path,
    *,
    episode_key: str | None = None,
) -> None:
    """
    Déplace les fichiers existants (storage + symlinks video) vers le sandbox.

    existing_dir est dans video_dir (symlinks). On suit les symlinks pour
    trouver le vrai chemin storage, puis on déplace et supprime les symlinks.

    Pour les séries, si episode_key est fourni (ex: "S01E03"), seuls les
    fichiers de cet épisode sont sandboxés au lieu du dossier entier.
    Pour les films, tout le dossier est déplacé (comportement original).
    """
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    # 1. Trouver le vrai chemin storage via les symlinks
    storage_path = _resolve_storage_path(existing_dir, storage_dir)

    if not storage_path or not storage_path.exists() or not storage_path.is_dir():
        logger.warning(
            "Sandbox: impossible de résoudre le chemin storage pour {}",
            existing_dir,
        )
        return

    # Garde-fou critique : ne JAMAIS sandboxer un répertoire de subdivision
    if _is_subdivision_path(storage_path):
        logger.error(
            "BLOQUÉ: tentative de sandbox sur un répertoire de subdivision {} "
            "(source: {}). Opération annulée pour protéger la vidéothèque.",
            storage_path,
            existing_dir,
        )
        return

    try:
        relative = storage_path.relative_to(storage_dir)
    except ValueError:
        relative = Path(storage_path.name)

    if episode_key:
        # Séries : ne sandboxer que les fichiers de l'épisode spécifique
        import re

        pattern = re.compile(re.escape(episode_key), re.IGNORECASE)
        moved = 0
        for item in storage_path.rglob("*"):
            if item.is_file() and pattern.search(item.name):
                item_rel = item.relative_to(storage_dir)
                dest = sandbox_dir / REPLACED_SUBDIR / item_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(dest))
                moved += 1
                logger.info("Sandbox (épisode) : {} → {}", item, dest)
        # Supprimer les symlinks correspondants dans video_dir
        for item in existing_dir.rglob("*"):
            if item.is_symlink() and pattern.search(item.name):
                item.unlink()
                logger.info("Symlink supprimé : {}", item)
        if moved == 0:
            logger.warning(
                "Sandbox: aucun fichier {} trouvé dans {}", episode_key, storage_path
            )
    else:
        # Films : déplacer tout le dossier sous la catégorie « ancienne version »
        dest = sandbox_dir / REPLACED_SUBDIR / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(storage_path), str(dest))
        logger.info("Sandbox (storage) : {} → {}", storage_path, dest)

        # Supprimer le répertoire de symlinks dans video_dir
        if existing_dir.exists() and existing_dir.is_dir():
            shutil.rmtree(str(existing_dir))
            logger.info("Symlinks supprimés : {}", existing_dir)


def _write_transfer_log(details: list[dict], storage_dir: Path) -> None:
    """Écrit un fichier JSON de log des transferts effectués."""
    from datetime import datetime

    log_dir = storage_dir / ".transfer_logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"transfer_{timestamp}.json"
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "count": len(details),
        "files": details,
    }
    try:
        log_file.write_text(json.dumps(log_data, ensure_ascii=False, indent=2))
        logger.info("Log de transfert : {}", log_file)
    except Exception as e:
        logger.warning("Impossible d'écrire le log de transfert : {}", e)


def _build_tree_data(transfers: list[dict], storage_dir: Path, video_dir: Path) -> dict:
    """
    Organise les transferts en arborescence pour le template.

    Returns:
        Dict avec 'movies' et 'series', chacun organisé hiérarchiquement.
    """
    # Pré-calcul : nombre et taille totale des nouveaux fichiers par groupe doublon
    _new_group_stats: dict[str, dict] = {}  # group_key → {count, total_size}
    for t in transfers:
        if t.get("has_duplicate"):
            gk = f"{t.get('title', '')}|{t.get('year')}"
            source = t.get("source")
            size = source.stat().st_size if source and source.exists() else 0
            if gk not in _new_group_stats:
                _new_group_stats[gk] = {"count": 0, "total_size": 0}
            _new_group_stats[gk]["count"] += 1
            _new_group_stats[gk]["total_size"] += size

    movies = []
    series = []

    for t in transfers:
        source = t.get("source")
        source_size = source.stat().st_size if source and source.exists() else 0

        pending = t.get("pending")
        # Infos doublon pour affichage dans le résumé
        duplicate_match = t.get("duplicate_match")
        duplicate_info = None
        if t.get("has_duplicate") and duplicate_match:
            quality = duplicate_match.quality
            existing_count = len(duplicate_match.existing_files)
            existing_total = sum(f.size_bytes for f in duplicate_match.existing_files)
            existing_avg = existing_total // existing_count if existing_count else 0

            gk = f"{t.get('title', '')}|{t.get('year')}"
            new_stats = _new_group_stats.get(gk, {"count": 1, "total_size": 0})
            new_count = new_stats["count"]
            new_avg = new_stats["total_size"] // new_count if new_count else 0

            duplicate_info = {
                "existing_title": duplicate_match.existing_title,
                "existing_dir": str(duplicate_match.existing_dir),
                "similarity_reason": duplicate_match.similarity_reason,
                "existing_file_count": existing_count,
                "existing_total_size": _format_size(existing_total),
                "existing_avg_size": _format_size(existing_avg),
                "new_file_count": new_count,
                "new_total_size": _format_size(new_stats["total_size"]),
                "new_avg_size": _format_size(new_avg),
            }
            if quality:
                duplicate_info.update(
                    {
                        "quality_existing": quality.existing_score,
                        "quality_new": quality.new_score,
                        "recommended": quality.recommended,
                        "existing_resolution": quality.existing_breakdown.get(
                            "resolution", "?"
                        ),
                        "existing_video_codec": quality.existing_breakdown.get(
                            "video_codec", "?"
                        ),
                        "existing_audio_codec": quality.existing_breakdown.get(
                            "audio_codec", "?"
                        ),
                        "existing_video_bitrate": quality.existing_breakdown.get(
                            "video_bitrate", "?"
                        ),
                        "existing_audio_bitrate": quality.existing_breakdown.get(
                            "audio_bitrate", "?"
                        ),
                        "new_resolution": quality.new_breakdown.get("resolution", "?"),
                        "new_video_codec": quality.new_breakdown.get(
                            "video_codec", "?"
                        ),
                        "new_audio_codec": quality.new_breakdown.get(
                            "audio_codec", "?"
                        ),
                        "new_video_bitrate": quality.new_breakdown.get(
                            "video_bitrate", "?"
                        ),
                        "new_audio_bitrate": quality.new_breakdown.get(
                            "audio_bitrate", "?"
                        ),
                    }
                )

        # Clé de groupe pour cascade série
        title = t.get("title", "")
        year = t.get("year")
        duplicate_group_key = f"{title}|{year}" if duplicate_info else None

        entry = {
            "new_filename": t["new_filename"],
            "source_name": source.name if source else "?",
            "source_size": _format_size(source_size) if source_size else "?",
            "storage_rel": "",
            "symlink_rel": "",
            "title": title,
            "year": year,
            "pending_id": pending.id if pending else None,
            "duplicate": duplicate_info,
            "duplicate_group_key": duplicate_group_key,
            "duplicate_resolution": t.get("duplicate_resolution"),
        }

        # Calculer les chemins relatifs pour l'affichage
        dest = t.get("destination")
        if dest and storage_dir:
            try:
                entry["storage_rel"] = str(dest.relative_to(storage_dir))
            except ValueError:
                entry["storage_rel"] = str(dest)

        symlink = t.get("symlink_destination")
        if symlink and video_dir:
            try:
                entry["symlink_rel"] = str(symlink.relative_to(video_dir))
            except ValueError:
                entry["symlink_rel"] = str(symlink)

        if t.get("is_series", False):
            series.append(entry)
        else:
            movies.append(entry)

    # Organiser les films par sous-répertoire
    movies_tree = _group_by_path(movies, key="symlink_rel", prefix="Films")

    # Organiser les séries par sous-répertoire
    series_tree = _group_by_path(series, key="symlink_rel", prefix="Series")

    duplicate_count = sum(1 for t in transfers if t.get("has_duplicate"))
    unresolved_count = sum(
        1
        for t in transfers
        if t.get("has_duplicate") and not t.get("duplicate_resolution")
    )

    # Saisons partielles : épisodes de nouvelles saisons pour des séries
    # qui ont aussi des doublons (même title+year, is_series, sans has_duplicate)
    dup_series_keys = {
        f"{t.get('title', '')}|{t.get('year')}"
        for t in transfers
        if t.get("has_duplicate") and t.get("is_series", False)
    }
    new_season_count = sum(
        1
        for t in transfers
        if t.get("is_series", False)
        and not t.get("has_duplicate")
        and f"{t.get('title', '')}|{t.get('year')}" in dup_series_keys
    )

    return {
        "movies": movies_tree,
        "series": series_tree,
        "total": len(transfers),
        "movie_count": len(movies),
        "series_count": len(series),
        "duplicate_count": duplicate_count,
        "unresolved_duplicate_count": unresolved_count,
        "new_season_episode_count": new_season_count,
    }


def _group_by_path(entries: list[dict], key: str, prefix: str) -> list[dict]:
    """
    Regroupe des entrées par leur chemin parent.

    Retourne une liste de groupes avec label (chemin parent) et items.
    """
    groups: dict[str, list[dict]] = defaultdict(list)

    for entry in entries:
        rel = entry.get(key, "")
        # Extraire le répertoire parent (sans le fichier)
        parts = Path(rel).parts
        if len(parts) > 1:
            # Supprimer le préfixe (Films/ ou Séries/) et le fichier
            parent_parts = parts[1:-1] if parts[0] == prefix else parts[:-1]
            parent = "/".join(parent_parts)
        else:
            parent = ""
        groups[parent].append(entry)

    result = []
    for path in sorted(groups.keys()):
        items = sorted(groups[path], key=lambda e: e["new_filename"])
        result.append({"path": path, "files": items})

    return result


# ═══════════════════════════════════════
# Logique de transfert web
# ═══════════════════════════════════════


def _update_db_paths(
    container, transfer: dict, destination: Path, symlink_dest
) -> None:
    """Met à jour file_path et symlink_path en DB après un transfert réussi."""
    from sqlmodel import select

    from src.infrastructure.persistence.database import get_session
    from src.infrastructure.persistence.models import (
        EpisodeModel,
        MovieModel,
        MoviePartModel,
    )

    session = next(get_session())
    try:
        storage_str = str(destination)
        symlink_str = str(symlink_dest) if symlink_dest else None

        movie_id = transfer.get("movie_id")
        part_number = transfer.get("movie_part_number")
        if movie_id and part_number is not None:
            # Partie non primaire : enregistrer une MoviePart, ne pas
            # ecraser le file_path de la fiche (porte par la Partie 1).
            existing_part = session.exec(
                select(MoviePartModel).where(
                    MoviePartModel.movie_id == int(movie_id),
                    MoviePartModel.part_number == int(part_number),
                )
            ).first()
            if existing_part:
                existing_part.file_path = storage_str
                existing_part.symlink_path = symlink_str
                session.add(existing_part)
            else:
                session.add(
                    MoviePartModel(
                        movie_id=int(movie_id),
                        part_number=int(part_number),
                        file_path=storage_str,
                        symlink_path=symlink_str,
                    )
                )
            session.commit()
        elif movie_id:
            movie = session.get(MovieModel, int(movie_id))
            if movie:
                movie.file_path = storage_str
                movie.symlink_path = symlink_str
                session.add(movie)
                session.commit()

        episode_id = transfer.get("episode_id")
        if episode_id:
            ep = session.get(EpisodeModel, int(episode_id))
            if ep:
                ep.file_path = storage_str
                ep.symlink_path = symlink_str
                session.add(ep)
                session.commit()
    finally:
        session.close()


async def _run_web_transfer(
    container,
    transfers: list[dict],
    progress: TransferProgress,
    *,
    dry_run: bool = False,
) -> None:
    """
    Exécute les transferts avec gestion des conflits et progression.

    En mode dry_run, simule le transfert sans toucher au système de fichiers.

    Pour chaque transfert :
    1. Vérifie les conflits (DUPLICATE / NAME_COLLISION)
    2. Si DUPLICATE → ignore automatiquement
    3. Si NAME_COLLISION ou SIMILAR_CONTENT → pause pour résolution
    4. Sinon → transfer_file()
    """
    try:
        settings = container.config()
        transferer = container.transferer_service(
            storage_dir=settings.storage_dir,
            video_dir=settings.video_dir,
        )

        storage_dir = settings.storage_dir
        video_dir = settings.video_dir
        mode_label = "Simulation" if dry_run else "Transfert"
        progress.total = len(transfers)
        progress.message = f"{mode_label} de {len(transfers)} fichier(s)…"

        def _extract_episode_key(transfer: dict) -> str | None:
            """Extrait SxxExx du nom de fichier si c'est une série."""
            if not transfer.get("is_series"):
                return None
            import re

            fn = transfer.get("new_filename", "")
            m = re.search(r"(S\d+E\d+)", fn, re.IGNORECASE)
            return m.group(1).upper() if m else None

        def _record_transfer(name: str, dest: Path, sym: Optional[Path]) -> None:
            """Enregistre les détails d'un transfert réussi."""
            progress.transferred_files.append(name)
            try:
                storage_rel = str(dest.relative_to(storage_dir))
            except ValueError:
                storage_rel = str(dest)
            symlink_rel = ""
            if sym:
                try:
                    symlink_rel = str(sym.relative_to(video_dir))
                except ValueError:
                    symlink_rel = str(sym)
            progress.transferred_details.append(
                {
                    "name": name,
                    "storage": storage_rel,
                    "symlink": symlink_rel,
                }
            )

        # Suivi des répertoires déjà déplacés vers sandbox (éviter de move N fois)
        _moved_to_sandbox: set[str] = set()

        for i, transfer in enumerate(transfers):
            source = transfer["source"]
            destination = transfer["destination"]
            symlink_dest = transfer.get("symlink_destination")
            new_filename = transfer.get("new_filename", "")
            source_name = source.name if hasattr(source, "name") else str(source)
            display_name = new_filename or source_name

            progress.current = i + 1
            progress.filename = source_name
            progress.message = f"{mode_label} : {source_name}"

            # Vérifier les doublons pré-transfert (titres similaires existants)
            duplicate_match = transfer.get("duplicate_match")
            pre_resolution = transfer.get("duplicate_resolution")

            # Résolution pré-faite au résumé batch → exécuter sans SSE pause
            if transfer.get("has_duplicate") and duplicate_match and pre_resolution:
                if pre_resolution == "keep_old":
                    if not dry_run:
                        _reject_source_to_sandbox(container, settings, source)
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu (pré) : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue

                elif pre_resolution == "keep_new":
                    if dry_run:
                        progress.transferred += 1
                        _record_transfer(display_name, destination, symlink_dest)
                        progress.message = (
                            f"[Simulation] Remplacement (pré) : {display_name}"
                        )
                    else:
                        # Sandbox : sandboxer l'épisode spécifique (séries)
                        # ou le dossier entier (films)
                        ep_key = _extract_episode_key(transfer)
                        sandbox_key = f"{duplicate_match.existing_dir}|{ep_key or '*'}"
                        if sandbox_key not in _moved_to_sandbox:
                            try:
                                sandbox_dir = _get_sandbox_dir(settings)
                                _sandbox_existing(
                                    duplicate_match.existing_dir,
                                    sandbox_dir,
                                    storage_dir,
                                    video_dir,
                                    episode_key=ep_key,
                                )
                            except Exception as e:
                                logger.warning(
                                    "Échec sandbox %s: %s — transfert quand même",
                                    duplicate_match.existing_dir,
                                    e,
                                )
                            _moved_to_sandbox.add(sandbox_key)

                        # Transférer le nouveau fichier (même si sandbox a échoué)
                        try:
                            result = transferer.transfer_file(
                                source,
                                destination,
                                create_symlink=True,
                                symlink_destination=symlink_dest,
                            )
                            if result.success:
                                progress.transferred += 1
                                _record_transfer(
                                    display_name, destination, symlink_dest
                                )
                            else:
                                if result.conflict:
                                    err = (
                                        f"Conflit {result.conflict.conflict_type.value} "
                                        f"avec {result.conflict.existing_path}"
                                    )
                                else:
                                    err = result.error or "Erreur inconnue"
                                logger.warning(
                                    "Échec transfert (pré-résolu) %s: %s",
                                    source_name,
                                    err,
                                )
                                progress.errors += 1
                                progress.error_files.append(f"{display_name} ({err})")
                        except Exception as e:
                            logger.warning("Erreur transfert %s: %s", source_name, e)
                            progress.errors += 1
                            progress.error_files.append(f"{display_name} ({e})")
                    progress.conflicts_resolved += 1
                    continue

                elif pre_resolution == "keep_both":
                    if not dry_run:
                        ep_key = _extract_episode_key(transfer)
                        sandbox_key = f"{duplicate_match.existing_dir}|{ep_key or '*'}"
                        if sandbox_key not in _moved_to_sandbox:
                            try:
                                sandbox_dir = _get_sandbox_dir(settings)
                                _sandbox_existing(
                                    duplicate_match.existing_dir,
                                    sandbox_dir,
                                    storage_dir,
                                    video_dir,
                                    episode_key=ep_key,
                                )
                                _moved_to_sandbox.add(sandbox_key)
                            except Exception as e:
                                logger.warning(
                                    "Erreur sandbox %s: %s",
                                    duplicate_match.existing_dir,
                                    e,
                                )
                    progress.conflicts_resolved += 1
                    # Le nouveau sera transféré normalement ci-dessous

                else:
                    # skip
                    progress.conflicts_resolved += 1
                    progress.message = f"Doublon passé (pré) : {display_name}"
                    await asyncio.sleep(0.1)
                    continue

            # Doublon non résolu au résumé → dialogue SSE interactif (comportement existant)
            elif transfer.get("has_duplicate") and duplicate_match:
                quality = duplicate_match.quality

                progress.conflict_pending = True
                progress.conflict_data = {
                    "type": "similar_content",
                    "filename": display_name,
                    "existing_path": str(duplicate_match.existing_dir),
                    "existing_name": duplicate_match.existing_title,
                    "existing_size": _format_size(
                        sum(f.size_bytes for f in duplicate_match.existing_files)
                    ),
                    "new_name": display_name,
                    "new_size": _format_size(
                        source.stat().st_size if source.exists() else 0
                    ),
                    "similarity_reason": duplicate_match.similarity_reason,
                    "existing_file_count": len(duplicate_match.existing_files),
                    "transfer_index": i,
                }

                # Ajouter les scores de qualité si disponibles
                if quality:
                    progress.conflict_data.update(
                        {
                            "quality_existing": quality.existing_score,
                            "quality_new": quality.new_score,
                            "recommended": quality.recommended,
                            "existing_resolution": quality.existing_breakdown.get(
                                "resolution", "?"
                            ),
                            "existing_video_codec": quality.existing_breakdown.get(
                                "video_codec", "?"
                            ),
                            "existing_audio_codec": quality.existing_breakdown.get(
                                "audio_codec", "?"
                            ),
                            "new_resolution": quality.new_breakdown.get(
                                "resolution", "?"
                            ),
                            "new_video_codec": quality.new_breakdown.get(
                                "video_codec", "?"
                            ),
                            "new_audio_codec": quality.new_breakdown.get(
                                "audio_codec", "?"
                            ),
                        }
                    )
                else:
                    # Fallback : extraire les infos via mediainfo
                    try:
                        best_existing = (
                            max(
                                duplicate_match.existing_files,
                                key=lambda f: f.size_bytes,
                            )
                            if duplicate_match.existing_files
                            else None
                        )
                        if best_existing:
                            existing_info = transferer._get_file_info(
                                best_existing.path
                            )
                            progress.conflict_data.update(
                                {
                                    "existing_resolution": existing_info.resolution
                                    or "?",
                                    "existing_video_codec": existing_info.video_codec
                                    or "?",
                                    "existing_audio_codec": existing_info.audio_codec
                                    or "?",
                                }
                            )
                        new_info = transferer._get_file_info(source)
                        progress.conflict_data.update(
                            {
                                "new_resolution": new_info.resolution or "?",
                                "new_video_codec": new_info.video_codec or "?",
                                "new_audio_codec": new_info.audio_codec or "?",
                            }
                        )
                    except Exception:
                        pass

                progress.conflict_event.clear()
                progress.message = (
                    f"Doublon détecté : {display_name} — en attente de résolution"
                )
                await progress.conflict_event.wait()

                choice = progress.conflict_choice
                progress.conflict_pending = False
                progress.conflict_data = None
                progress.conflict_choice = None

                if choice == "keep_old":
                    if not dry_run:
                        _reject_source_to_sandbox(container, settings, source)
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue

                elif choice == "keep_new":
                    if dry_run:
                        progress.transferred += 1
                        _record_transfer(display_name, destination, symlink_dest)
                        progress.message = f"[Simulation] Remplacement : {display_name}"
                    else:
                        # Sandbox : sandboxer l'épisode spécifique (séries)
                        # ou le dossier entier (films)
                        ep_key = _extract_episode_key(transfer)
                        sandbox_key = f"{duplicate_match.existing_dir}|{ep_key or '*'}"
                        if sandbox_key not in _moved_to_sandbox:
                            try:
                                sandbox_dir = _get_sandbox_dir(settings)
                                _sandbox_existing(
                                    duplicate_match.existing_dir,
                                    sandbox_dir,
                                    storage_dir,
                                    video_dir,
                                    episode_key=ep_key,
                                )
                            except Exception as e:
                                logger.warning(
                                    "Échec sandbox %s: %s — transfert quand même",
                                    duplicate_match.existing_dir,
                                    e,
                                )
                            _moved_to_sandbox.add(sandbox_key)
                        # Transférer le nouveau normalement
                        try:
                            result = transferer.transfer_file(
                                source,
                                destination,
                                create_symlink=True,
                                symlink_destination=symlink_dest,
                            )
                            if result.success:
                                progress.transferred += 1
                                _record_transfer(
                                    display_name, destination, symlink_dest
                                )
                            else:
                                progress.errors += 1
                                progress.error_files.append(display_name)
                        except Exception as e:
                            logger.warning("Erreur transfert %s: %s", source_name, e)
                            progress.errors += 1
                            progress.error_files.append(display_name)
                    progress.conflicts_resolved += 1
                    continue

                elif choice == "keep_both":
                    if not dry_run:
                        ep_key = _extract_episode_key(transfer)
                        sandbox_key = f"{duplicate_match.existing_dir}|{ep_key or '*'}"
                        if sandbox_key not in _moved_to_sandbox:
                            try:
                                sandbox_dir = _get_sandbox_dir(settings)
                                _sandbox_existing(
                                    duplicate_match.existing_dir,
                                    sandbox_dir,
                                    storage_dir,
                                    video_dir,
                                    episode_key=ep_key,
                                )
                                _moved_to_sandbox.add(sandbox_key)
                            except Exception as e:
                                logger.warning(
                                    "Erreur sandbox %s: %s",
                                    duplicate_match.existing_dir,
                                    e,
                                )
                    # Le nouveau sera transféré normalement ci-dessous
                    progress.conflicts_resolved += 1

                else:
                    progress.conflicts_resolved += 1
                    progress.message = f"Doublon passé : {display_name}"
                    await asyncio.sleep(0.1)
                    continue

            # Vérifier les conflits de fichier (hash)
            conflict = transferer.check_conflict(source, destination)

            if conflict:
                from src.services.transferer import ConflictType

                if conflict.conflict_type == ConflictType.DUPLICATE:
                    progress.duplicates_ignored += 1
                    progress.duplicate_files.append(display_name)
                    progress.message = (
                        f"[Simulation] Doublon : {display_name}"
                        if dry_run
                        else f"Doublon ignoré : {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue

                elif conflict.conflict_type in (
                    ConflictType.NAME_COLLISION,
                    ConflictType.SIMILAR_CONTENT,
                ):
                    existing_path = conflict.existing_path
                    existing_size = (
                        existing_path.stat().st_size if existing_path.exists() else 0
                    )
                    new_size = source.stat().st_size if source.exists() else 0

                    progress.conflict_pending = True
                    progress.conflict_data = {
                        "type": conflict.conflict_type.value,
                        "filename": display_name,
                        "existing_path": str(existing_path),
                        "existing_name": existing_path.name,
                        "existing_size": _format_size(existing_size),
                        "new_name": display_name,
                        "new_size": _format_size(new_size),
                        "transfer_index": i,
                    }

                    try:
                        existing_info = transferer._get_file_info(existing_path)
                        new_info = transferer._get_file_info(source)
                        progress.conflict_data.update(
                            {
                                "existing_resolution": existing_info.resolution or "?",
                                "existing_video_codec": existing_info.video_codec
                                or "?",
                                "existing_audio_codec": existing_info.audio_codec
                                or "?",
                                "new_resolution": new_info.resolution or "?",
                                "new_video_codec": new_info.video_codec or "?",
                                "new_audio_codec": new_info.audio_codec or "?",
                            }
                        )
                    except Exception:
                        progress.conflict_data.update(
                            {
                                "existing_resolution": "?",
                                "existing_video_codec": "?",
                                "existing_audio_codec": "?",
                                "new_resolution": "?",
                                "new_video_codec": "?",
                                "new_audio_codec": "?",
                            }
                        )

                    progress.conflict_event.clear()
                    progress.message = (
                        f"Conflit : {display_name} — en attente de résolution"
                    )
                    await progress.conflict_event.wait()

                    choice = progress.conflict_choice
                    progress.conflict_pending = False
                    progress.conflict_data = None
                    progress.conflict_choice = None

                    if choice == "keep_old":
                        if not dry_run:
                            _reject_source_to_sandbox(container, settings, source)
                        progress.conflicts_resolved += 1
                        progress.message = (
                            f"Conflit résolu : ancien conservé pour {display_name}"
                        )
                        await asyncio.sleep(0.1)
                        continue

                    elif choice == "keep_new":
                        if dry_run:
                            progress.transferred += 1
                            _record_transfer(display_name, destination, symlink_dest)
                            progress.message = (
                                f"[Simulation] Remplacement : {display_name}"
                            )
                        else:
                            try:
                                trash_dir = getattr(
                                    settings, "trash_dir", Path("/tmp/cineorg_trash")
                                )
                                transferer.move_to_staging(existing_path, trash_dir)
                                result = transferer.transfer_file(
                                    source,
                                    destination,
                                    create_symlink=True,
                                    symlink_destination=symlink_dest,
                                )
                                if result.success:
                                    progress.transferred += 1
                                    _record_transfer(
                                        display_name, destination, symlink_dest
                                    )
                                else:
                                    if result.conflict:
                                        err = (
                                            f"Conflit {result.conflict.conflict_type.value} "
                                            f"avec {result.conflict.existing_path}"
                                        )
                                    else:
                                        err = result.error or "Erreur inconnue"
                                    logger.warning(
                                        "Échec transfert (SSE) %s: %s",
                                        source_name,
                                        err,
                                    )
                                    progress.errors += 1
                                    progress.error_files.append(
                                        f"{display_name} ({err})"
                                    )
                            except Exception as e:
                                logger.warning(
                                    "Erreur transfert %s: %s", source_name, e
                                )
                                progress.errors += 1
                                progress.error_files.append(f"{display_name} ({e})")
                        progress.conflicts_resolved += 1
                        continue

                    elif choice == "keep_both":
                        stem = destination.stem
                        suffix = destination.suffix
                        destination = destination.with_name(f"{stem} (2){suffix}")
                        if symlink_dest:
                            sym_stem = symlink_dest.stem
                            sym_suffix = symlink_dest.suffix
                            symlink_dest = symlink_dest.with_name(
                                f"{sym_stem} (2){sym_suffix}"
                            )
                        progress.conflicts_resolved += 1

                    else:
                        progress.conflicts_resolved += 1
                        progress.message = f"Conflit passé : {display_name}"
                        await asyncio.sleep(0.1)
                        continue

            # Transfert normal (pas de conflit ou conflit résolu avec keep_both)
            if dry_run:
                progress.transferred += 1
                _record_transfer(display_name, destination, symlink_dest)
                progress.message = f"[Simulation] {display_name} → OK"
                await asyncio.sleep(0.15)
            else:
                try:
                    result = transferer.transfer_file(
                        source,
                        destination,
                        create_symlink=True,
                        symlink_destination=symlink_dest,
                    )
                    if result.success:
                        progress.transferred += 1
                        _record_transfer(display_name, destination, symlink_dest)
                        progress.message = f"Transféré : {display_name}"
                    else:
                        if result.conflict:
                            error_msg = (
                                f"Conflit {result.conflict.conflict_type.value} "
                                f"avec {result.conflict.existing_path}"
                            )
                        else:
                            error_msg = result.error or "Erreur inconnue"
                        logger.warning("Échec transfert %s: %s", source_name, error_msg)
                        progress.errors += 1
                        progress.error_files.append(f"{display_name} ({error_msg})")
                except Exception as e:
                    logger.exception("Erreur transfert %s: %s", source_name, e)
                    progress.errors += 1
                    progress.error_files.append(display_name)

            # Laisser respirer l'event loop
            if i % 2 == 0:
                await asyncio.sleep(0)

        # Mettre à jour file_path et symlink_path en DB pour tous les transferts réussis
        if not dry_run:
            for transfer in transfers:
                destination = transfer.get("destination")
                symlink_dest = transfer.get("symlink_destination")
                if destination and Path(str(destination)).exists():
                    try:
                        _update_db_paths(
                            container, transfer, Path(str(destination)), symlink_dest
                        )
                    except Exception as e:
                        logger.warning(
                            "Erreur mise à jour DB pour %s: %s",
                            transfer.get("new_filename"),
                            e,
                        )

        progress.message = "Simulation terminée" if dry_run else "Transfert terminé"
        progress.complete = True

        # Log de transfert pour traçabilité
        if not dry_run and progress.transferred_details:
            _write_transfer_log(progress.transferred_details, storage_dir)

    except Exception as e:
        logger.exception("Erreur lors du transfert web: %s", e)
        progress.error = str(e)
        progress.complete = True


# ═══════════════════════════════════════
# Routes
# ═══════════════════════════════════════


@router.get("/", response_class=HTMLResponse)
async def transfer_index(request: Request):
    """Page principale du transfert — shell immédiat avec chargement HTMX."""
    return templates.TemplateResponse(
        request,
        "transfer/index.html",
        {},
    )


@router.post("/prepare", response_class=HTMLResponse)
async def transfer_prepare(request: Request):
    """Lance la préparation du batch en arrière-plan avec suivi SSE."""
    container = request.app.state.container
    validation_service = container.validation_service()

    validated_list = validation_service.list_validated()
    pending_count = len(validation_service.list_pending())

    if not validated_list:
        return templates.TemplateResponse(
            request,
            "transfer/_batch_content.html",
            {
                "has_transfers": False,
                "pending_count": pending_count,
                "tree_data": None,
            },
        )

    # Créer l'état de progression
    progress = BatchPrepareProgress()
    progress.total = len(validated_list)
    request.app.state.batch_prepare_progress = progress

    # Lancer la préparation en arrière-plan
    app_state = request.app.state
    task = asyncio.create_task(
        _prepare_batch_async(container, validated_list, progress, app_state)
    )
    app_state.batch_prepare_task = task

    return templates.TemplateResponse(
        request,
        "transfer/_prepare_progress.html",
        {"progress": progress},
    )


async def _prepare_batch_async(
    container,
    validated_list: list,
    progress: BatchPrepareProgress,
    app_state,
) -> None:
    """Prépare le batch en arrière-plan avec callback de progression."""
    from io import StringIO

    from rich.console import Console as RichConsole

    from src.adapters.cli.batch_builder import build_transfers_batch

    silent_console = RichConsole(file=StringIO(), quiet=True)
    import src.adapters.cli.batch_builder as bb

    original_console = bb.console
    bb.console = silent_console

    try:
        settings = container.config()
        storage_dir = settings.storage_dir
        video_dir = settings.video_dir

        def _on_progress(current: int, total: int, filename: str) -> None:
            progress.current = current
            progress.total = total
            progress.filename = filename
            progress.message = f"Préparation : {filename}"

        transfers = await build_transfers_batch(
            validated_list,
            container,
            storage_dir,
            video_dir,
            on_progress=_on_progress,
        )

        # Stocker les résultats
        app_state.transfer_batch = transfers
        app_state.transfer_storage_dir = storage_dir
        app_state.transfer_video_dir = video_dir

        progress.message = "Préparation terminée"
        progress.complete = True

    except Exception as e:
        logger.exception("Erreur préparation batch: %s", e)
        progress.error = str(e)
        progress.complete = True
    finally:
        bb.console = original_console


@router.get("/prepare-progress")
async def transfer_prepare_progress(request: Request):
    """SSE endpoint pour le suivi de la préparation du batch."""
    progress = getattr(request.app.state, "batch_prepare_progress", None)

    async def event_stream():
        if progress is None:
            yield 'event: error\ndata: {"message": "Aucune préparation en cours"}\n\n'
            return

        last_sent = ""
        while not progress.complete:
            data = json.dumps(
                {
                    "current": progress.current,
                    "total": progress.total,
                    "filename": progress.filename,
                    "message": progress.message,
                },
                ensure_ascii=False,
            )

            if data != last_sent:
                yield f"event: progress\ndata: {data}\n\n"
                last_sent = data

            await asyncio.sleep(0.4)

        if progress.error:
            error_data = json.dumps({"message": progress.error}, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"
        else:
            yield "event: complete\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/batch", response_class=HTMLResponse)
async def transfer_batch(request: Request):
    """Retourne le contenu du batch préparé (appelé après la fin du SSE)."""
    container = request.app.state.container
    validation_service = container.validation_service()
    pending_count = len(validation_service.list_pending())

    transfers = getattr(request.app.state, "transfer_batch", None)
    if not transfers:
        return templates.TemplateResponse(
            request,
            "transfer/_batch_content.html",
            {
                "has_transfers": False,
                "pending_count": pending_count,
                "tree_data": None,
            },
        )

    storage_dir = request.app.state.transfer_storage_dir
    video_dir = request.app.state.transfer_video_dir
    tree_data = _build_tree_data(transfers, storage_dir, video_dir)

    return templates.TemplateResponse(
        request,
        "transfer/_batch_content.html",
        {
            "has_transfers": True,
            "pending_count": pending_count,
            "tree_data": tree_data,
        },
    )


@router.post("/start", response_class=HTMLResponse)
async def transfer_start(request: Request):
    """Lance le transfert (ou simulation) en arrière-plan."""
    container = request.app.state.container
    dry_run = request.query_params.get("dry_run") == "1"

    # Vérifier qu'un transfert n'est pas déjà en cours
    existing = getattr(request.app.state, "transfer_progress", None)
    if existing and not existing.complete:
        return HTMLResponse(
            '<div class="action-msg action-warning">'
            "Un transfert est déjà en cours."
            "</div>"
        )

    # Récupérer le batch préparé
    transfers = getattr(request.app.state, "transfer_batch", None)
    if not transfers:
        return HTMLResponse(
            '<div class="action-msg action-error">'
            "Aucun transfert préparé. Rechargez la page."
            "</div>"
        )

    # Créer l'état de progression
    progress = TransferProgress()
    progress.dry_run = dry_run
    request.app.state.transfer_progress = progress

    # Lancer en arrière-plan
    task = asyncio.create_task(
        _run_web_transfer(container, transfers, progress, dry_run=dry_run)
    )
    request.app.state.transfer_task = task

    return templates.TemplateResponse(
        request,
        "transfer/_progress.html",
        {"progress": progress},
    )


@router.get("/progress")
async def transfer_progress_sse(request: Request):
    """SSE endpoint pour le suivi de progression du transfert."""
    progress = getattr(request.app.state, "transfer_progress", None)

    async def event_stream():
        if progress is None:
            yield 'event: error\ndata: {"message": "Aucun transfert en cours"}\n\n'
            return

        last_sent = ""
        while not progress.complete:
            # Conflit en attente ?
            if progress.conflict_pending and progress.conflict_data:
                conflict_json = json.dumps(progress.conflict_data, ensure_ascii=False)
                yield f"event: conflict\ndata: {conflict_json}\n\n"
                # Attendre que le conflit soit résolu avant de continuer
                await progress.conflict_event.wait()
                # Petit délai pour laisser le temps au front de se mettre à jour
                await asyncio.sleep(0.3)
                continue

            # Progression normale
            data = json.dumps(
                {
                    "current": progress.current,
                    "total": progress.total,
                    "filename": progress.filename,
                    "message": progress.message,
                    "transferred": progress.transferred,
                    "duplicates": progress.duplicates_ignored,
                },
                ensure_ascii=False,
            )

            if data != last_sent:
                yield f"event: progress\ndata: {data}\n\n"
                last_sent = data

            await asyncio.sleep(0.4)

        # Envoyer le dernier état de progression (compteur final)
        final_progress = json.dumps(
            {
                "current": progress.total,
                "total": progress.total,
                "filename": "",
                "message": progress.message,
                "transferred": progress.transferred,
                "duplicates": progress.duplicates_ignored,
            },
            ensure_ascii=False,
        )
        yield f"event: progress\ndata: {final_progress}\n\n"
        await asyncio.sleep(0.2)

        # Résultat final
        if progress.error:
            error_data = json.dumps({"message": progress.error}, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"
        else:
            complete_data = json.dumps(
                {
                    "transferred": progress.transferred,
                    "duplicates_ignored": progress.duplicates_ignored,
                    "conflicts_resolved": progress.conflicts_resolved,
                    "errors": progress.errors,
                    "transferred_files": progress.transferred_files,
                    "transferred_details": progress.transferred_details,
                    "duplicate_files": progress.duplicate_files,
                    "error_files": progress.error_files,
                },
                ensure_ascii=False,
            )
            yield f"event: complete\ndata: {complete_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/send-back/{pending_id}", response_class=HTMLResponse)
async def send_back(request: Request, pending_id: str):
    """Renvoie un fichier validé en statut pending pour re-validation.

    Pour les séries : renvoie aussi tous les épisodes de la même série
    (même selected_candidate_id) — cascade inverse de l'auto-validation.
    """
    container = request.app.state.container
    validation_service = container.validation_service()
    pending = validation_service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    candidate_id = pending.selected_candidate_id
    validation_service.reset_to_pending(pending)

    # Cascade inverse pour les séries : renvoyer tous les épisodes
    # ayant le même candidat TVDB (miroir de _auto_validate_series_episodes)
    cascade_count = 0
    if candidate_id:
        validated_list = validation_service.list_validated()
        for other in validated_list:
            if other.id != pending_id and other.selected_candidate_id == candidate_id:
                validation_service.reset_to_pending(other)
                cascade_count += 1

    if cascade_count > 0:
        msg = f"Fichier + {cascade_count} épisode(s) renvoyé(s) en validation."
    else:
        msg = "Fichier renvoyé en validation."

    response = HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        f"{msg}"
        "</div>"
    )
    response.headers["HX-Redirect"] = "/validation"
    return response


@router.post("/resolve-duplicate", response_class=HTMLResponse)
async def resolve_duplicate(
    request: Request,
    title: str = Form(...),
    year: str = Form(""),
    choice: str = Form(...),
):
    """Résout un doublon pré-transfert avec cascade série (même title+year)."""
    transfers = getattr(request.app.state, "transfer_batch", None)
    if not transfers:
        return HTMLResponse(
            '<div class="action-msg action-error">Aucun batch en cours.</div>',
            status_code=400,
        )

    year_val = year if year else None
    resolved_count = 0
    for t in transfers:
        if (
            t.get("has_duplicate")
            and t.get("title", "") == title
            and str(t.get("year", "") or "") == str(year_val or "")
        ):
            t["duplicate_resolution"] = choice
            resolved_count += 1

    if resolved_count == 0:
        return HTMLResponse(
            '<div class="action-msg action-warning">Aucun doublon trouvé.</div>'
        )

    # Retourner l'arborescence mise à jour
    storage_dir = request.app.state.transfer_storage_dir
    video_dir = request.app.state.transfer_video_dir
    tree_data = _build_tree_data(transfers, storage_dir, video_dir)

    return templates.TemplateResponse(
        request,
        "transfer/_batch_tree_and_alert.html",
        {"tree_data": tree_data},
    )


@router.post("/resolve-conflict", response_class=HTMLResponse)
async def resolve_conflict(
    request: Request,
    choice: str = Form(...),
):
    """Résout un conflit en attente."""
    progress = getattr(request.app.state, "transfer_progress", None)

    if progress is None or not progress.conflict_pending:
        return HTMLResponse(
            '<div class="action-msg action-warning">Aucun conflit en attente.</div>'
        )

    # Enregistrer le choix et débloquer le transfert
    progress.conflict_choice = choice
    progress.conflict_event.set()

    return HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        "Conflit résolu, transfert en cours…"
        "</div>"
    )
