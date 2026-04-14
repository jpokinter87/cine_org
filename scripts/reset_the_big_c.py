"""
Script one-shot : remettre "The Big C" en etat "serie tout juste telechargee".

Objectif : permettre de tester le plan 42-01 end-to-end sur la serie
complete (44 fichiers) et non uniquement sur les 4 pendings S04E05-E08.

Operations :
1. DB
   - DELETE 4 pending_validations REJECTED pour S04E05-E08 + video_files lies
   - DELETE 40 episodes (series_id=1053)
   - DELETE 40 video_files lies par file_path storage
   - DELETE 40 hardlinks rows (storage_path sous la serie)
   - KEEP SeriesModel id=1053 (sera re-associe au prochain workflow)

2. Fichiers physiques
   - rm 40 hardlinks dans downloads (noms scene deja existants)
   - rm 40 symlinks dans video (cibles du mv qui suit)
   - mv 40 fichiers storage -> downloads avec renommage pattern scene
     `The.Big.C.S{NN}E{MM}.mkv`
   - rmdir arborescence vide storage + video

Mode par defaut : dry-run (affichage seul). Passer --apply pour executer.

Usage :
    uv run python -m scripts.reset_the_big_c            # dry-run
    uv run python -m scripts.reset_the_big_c --apply    # execution reelle
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlmodel import Session, create_engine, select

from src.config import Settings
from src.infrastructure.persistence.database import init_db, get_engine
from src.infrastructure.persistence.models import (
    EpisodeModel,
    HardlinkModel,
    PendingValidationModel,
    SeriesModel,
    VideoFileModel,
)


SERIES_TITLE = "The Big C"
STORAGE_SERIES_ROOT = Path(
    "/media/NAS64/Series/TV/B/Ba-Bl/The Big C (2010)"
)
VIDEO_SERIES_ROOT = Path(
    "/media/Serveur/Collection/Series/TV/B/Ba-Bl/The Big C (2010)"
)
DOWNLOADS_SERIES_ROOT = Path(
    "/media/NAS64/temp/Séries/The Big C (2010)   (Multi) (1080p)"
)


def _scene_name(season: int, episode: int) -> str:
    return f"The.Big.C.S{season:02d}E{episode:02d}.mkv"


def _downloads_target(season: int, episode: int) -> Path:
    return DOWNLOADS_SERIES_ROOT / f"Saison {season:02d}" / _scene_name(
        season, episode
    )


def _load_plan(session: Session) -> dict:
    """Construit le plan d'operations a partir de la DB."""
    # Serie
    series = session.exec(
        select(SeriesModel).where(SeriesModel.title == SERIES_TITLE)
    ).first()
    if series is None:
        raise RuntimeError(f"Serie '{SERIES_TITLE}' introuvable en DB.")

    # Episodes
    episodes = session.exec(
        select(EpisodeModel).where(EpisodeModel.series_id == series.id)
    ).all()

    # VideoFiles associes (par path = episode.file_path)
    storage_paths = [e.file_path for e in episodes if e.file_path]
    video_files = []
    for p in storage_paths:
        vf = session.exec(
            select(VideoFileModel).where(VideoFileModel.path == p)
        ).first()
        if vf is not None:
            video_files.append(vf)

    # Pendings REJECTED avec filename Big C
    pendings_rejected = session.exec(
        select(PendingValidationModel).where(
            PendingValidationModel.validation_status == "rejected"
        )
    ).all()
    big_c_pendings = []
    pending_vfs = []
    for p in pendings_rejected:
        vf = session.exec(
            select(VideoFileModel).where(VideoFileModel.id == p.video_file_id)
        ).first()
        if vf is not None and "Big.C" in (vf.filename or ""):
            big_c_pendings.append(p)
            pending_vfs.append(vf)

    # Hardlinks a supprimer (storage_path sous la serie)
    hardlinks_rows = session.exec(
        select(HardlinkModel).where(
            HardlinkModel.storage_path.like(f"{STORAGE_SERIES_ROOT}%")
        )
    ).all()

    # Fichiers physiques
    hardlink_files_to_rm = [
        _downloads_target(e.season_number, e.episode_number)
        for e in episodes
    ]
    symlinks_to_rm = [
        Path(e.symlink_path) for e in episodes if e.symlink_path
    ]
    moves = [
        (
            Path(e.file_path),
            _downloads_target(e.season_number, e.episode_number),
        )
        for e in episodes
        if e.file_path
    ]

    return {
        "series": series,
        "episodes": episodes,
        "video_files": video_files,
        "pendings_rejected": big_c_pendings,
        "pending_video_files": pending_vfs,
        "hardlinks_rows": hardlinks_rows,
        "hardlink_files_to_rm": hardlink_files_to_rm,
        "symlinks_to_rm": symlinks_to_rm,
        "moves": moves,
    }


def _print_plan(plan: dict) -> None:
    """Affiche le plan en mode dry-run."""
    print("=" * 70)
    print(f"SERIE : {plan['series'].title} "
          f"(id={plan['series'].id}, tvdb_id={plan['series'].tvdb_id})")
    print("=" * 70)

    print(f"\n[DB] {len(plan['episodes'])} episodes à supprimer")
    for e in plan["episodes"][:5]:
        print(f"  - id={e.id} S{e.season_number:02d}E{e.episode_number:02d} "
              f"path={e.file_path}")
    if len(plan["episodes"]) > 5:
        print(f"  ... et {len(plan['episodes']) - 5} autres")

    print(f"\n[DB] {len(plan['video_files'])} video_files storage à supprimer")
    print(f"\n[DB] {len(plan['pendings_rejected'])} pendings REJECTED "
          f"(+ {len(plan['pending_video_files'])} video_files downloads) à supprimer")
    for p in plan["pendings_rejected"]:
        vf = next((v for v in plan["pending_video_files"]
                   if v.id == p.video_file_id), None)
        if vf:
            print(f"  - pending id={p.id} {vf.filename}")

    print(f"\n[DB] {len(plan['hardlinks_rows'])} hardlinks rows à supprimer")

    print(f"\n[FS] {len(plan['hardlink_files_to_rm'])} hardlinks downloads à rm")
    for p in plan["hardlink_files_to_rm"][:3]:
        print(f"  - rm {p}")
    print("  ...")

    print(f"\n[FS] {len(plan['symlinks_to_rm'])} symlinks video à rm")
    for p in plan["symlinks_to_rm"][:3]:
        print(f"  - unlink {p}")
    print("  ...")

    print(f"\n[FS] {len(plan['moves'])} fichiers storage à mv + rename")
    for src, dst in plan["moves"][:3]:
        print(f"  - mv {src.name}\n       -> {dst}")
    print("  ...")

    print("\n[FS] rmdir arborescences vides :")
    print(f"  - {STORAGE_SERIES_ROOT} (+ sous-dossiers Saison NN)")
    print(f"  - {VIDEO_SERIES_ROOT} (+ sous-dossiers)")

    print("\n" + "=" * 70)
    print("Mode DRY-RUN : aucune action effectuee. Relance avec --apply.")
    print("=" * 70)


def _apply(plan: dict, session: Session) -> None:
    """Execute les operations du plan."""
    print("\n>>> APPLY : execution reelle <<<\n")

    # 1. DB : supprimer pendings REJECTED + video_files lies
    for p in plan["pendings_rejected"]:
        session.delete(p)
    for vf in plan["pending_video_files"]:
        session.delete(vf)
    print(f"[DB] {len(plan['pendings_rejected'])} pendings REJECTED + "
          f"{len(plan['pending_video_files'])} video_files supprimes")

    # 2. DB : supprimer episodes + video_files storage + hardlinks rows
    for e in plan["episodes"]:
        session.delete(e)
    for vf in plan["video_files"]:
        session.delete(vf)
    for h in plan["hardlinks_rows"]:
        session.delete(h)
    session.commit()
    print(f"[DB] {len(plan['episodes'])} episodes + "
          f"{len(plan['video_files'])} video_files + "
          f"{len(plan['hardlinks_rows'])} hardlinks rows supprimes")

    # 3. FS : rm hardlinks downloads
    rm_count = 0
    for p in plan["hardlink_files_to_rm"]:
        if p.exists() or p.is_symlink():
            p.unlink()
            rm_count += 1
    print(f"[FS] {rm_count}/{len(plan['hardlink_files_to_rm'])} "
          f"hardlinks downloads supprimes")

    # 4. FS : rm symlinks video
    sym_count = 0
    for p in plan["symlinks_to_rm"]:
        if p.exists() or p.is_symlink():
            p.unlink()
            sym_count += 1
    print(f"[FS] {sym_count}/{len(plan['symlinks_to_rm'])} "
          f"symlinks video supprimes")

    # 5. FS : mv + rename fichiers storage -> downloads
    mv_count = 0
    for src, dst in plan["moves"]:
        if not src.exists():
            print(f"[!] Source manquante : {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        mv_count += 1
    print(f"[FS] {mv_count}/{len(plan['moves'])} fichiers deplaces et renommes")

    # 6. FS : rmdir arborescences vides
    for root in (STORAGE_SERIES_ROOT, VIDEO_SERIES_ROOT):
        if not root.exists():
            continue
        # Remonter depuis les sous-dossiers vers la racine
        for sub in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
            if sub.is_dir():
                try:
                    sub.rmdir()
                except OSError:
                    pass
        try:
            root.rmdir()
            print(f"[FS] rmdir {root}")
        except OSError as exc:
            print(f"[!] Impossible de rmdir {root} : {exc}")

    print("\n>>> APPLY termine. <<<")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Execute reellement les operations (sinon dry-run)."
    )
    args = parser.parse_args()

    # Declenche init_db pour appliquer la migration is_extra (phase 42-01)
    # si la DB reelle n'a pas encore ete ouverte par l'appli.
    init_db()
    engine = get_engine()

    with Session(engine) as session:
        plan = _load_plan(session)
        _print_plan(plan)
        if args.apply:
            _apply(plan, session)

    return 0


if __name__ == "__main__":
    sys.exit(main())
