"""
Cache persistant des rapports d'analyse cleanup.

Sauvegarde et charge les rapports en JSON pour eviter de
re-analyser le repertoire video a chaque commande.
"""

import json
import time
from pathlib import Path
from typing import Optional

from .dataclasses import (
    BrokenSymlinkInfo,
    CleanupReport,
    DuplicateSymlink,
    MisplacedSymlink,
    SubdivisionPlan,
)

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
                "out_of_range_items": [
                    [str(src), str(dst)] for src, dst in o.out_of_range_items
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
            out_of_range_items=[
                (Path(pair[0]), Path(pair[1]))
                for pair in o.get("out_of_range_items", [])
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
