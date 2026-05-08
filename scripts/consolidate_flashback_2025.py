"""
Consolidation Flashback (2025) : fusionne 3 fiches DB éclatées en une seule
et déplace 12 fichiers vers le bon dossier storage.

Avant :
  - id=1067 : 4 ep sous FLASHBACK (2014)/Saison 01/  (titres anglais erronés)
  - id=1068 : 2 ep sous Flashback (2011)/Saison 01/  (titres vides)
  - id=1069 : 6 ep sous Flashback (2025) (2025)/Saison 02/  (double année)

Après :
  - id=1069 : 12 ep sous Flashback (2025)/Saison 01/ + Saison 02/ avec
              titres TVDB officiels (Épisode 1 → Épisode 12)
  - id=1067 et id=1068 supprimées
  - Anciens dossiers retirés s'ils sont vides

Usage :
  uv run python scripts/consolidate_flashback_2025.py            # dry-run
  uv run python scripts/consolidate_flashback_2025.py --apply    # exécution
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlmodel import Session, create_engine, select

from src.config import Settings
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


STORAGE_ROOT = Path("/media/NAS64/Series/TV/E-F/Fe-Fz")
VIDEO_ROOT = Path("/media/Serveur/Collection/Series/TV/E-F/Fe-Fz")
TARGET_DIRNAME = "Flashback (2025)"
LANG_TECH_SUFFIX = "FR x265 1080p"


def planned_filename(season: int, episode: int) -> str:
    """Nouveau nom canonique du fichier."""
    return f"Flashback (2025) - S{season:02d}E{episode:02d} - Épisode {(season - 1) * 6 + episode} - {LANG_TECH_SUFFIX}.mkv"


def planned_storage_path(season: int, episode: int) -> Path:
    return STORAGE_ROOT / TARGET_DIRNAME / f"Saison {season:02d}" / planned_filename(season, episode)


def planned_video_path(season: int, episode: int) -> Path:
    return VIDEO_ROOT / TARGET_DIRNAME / f"Saison {season:02d}" / planned_filename(season, episode)


def main(apply: bool) -> int:
    engine = create_engine(Settings().database_url)
    moves: list[tuple[EpisodeModel, Path, Path]] = []  # (ep, new_file, new_sym)

    with Session(engine) as session:
        # Charger les 12 episodes
        all_eps: list[EpisodeModel] = []
        for sid in (1067, 1068, 1069):
            all_eps.extend(
                session.exec(select(EpisodeModel).where(EpisodeModel.series_id == sid)).all()
            )
        if len(all_eps) != 12:
            print(f"[!] Attendu 12 episodes, trouve {len(all_eps)}. Abandon.")
            return 1

        print(f"=== Plan de consolidation ({'APPLY' if apply else 'DRY-RUN'}) ===\n")

        for ep in sorted(all_eps, key=lambda e: (e.season_number, e.episode_number)):
            new_file = planned_storage_path(ep.season_number, ep.episode_number)
            new_sym = planned_video_path(ep.season_number, ep.episode_number)
            moves.append((ep, new_file, new_sym))
            print(f"  S{ep.season_number:02d}E{ep.episode_number:02d} (ep_id={ep.id}, series_id={ep.series_id})")
            print(f"    file: {ep.file_path}")
            print(f"      -> {new_file}")
            print(f"    sym : {ep.symlink_path}")
            print(f"      -> {new_sym}")

        if not apply:
            print("\n[dry-run] Aucune modification. Relancer avec --apply pour executer.")
            return 0

        # === APPLY ===
        print("\n=== Application ===")

        # 1. Creer les dossiers cibles
        for season in (1, 2):
            (STORAGE_ROOT / TARGET_DIRNAME / f"Saison {season:02d}").mkdir(parents=True, exist_ok=True)
            (VIDEO_ROOT / TARGET_DIRNAME / f"Saison {season:02d}").mkdir(parents=True, exist_ok=True)

        # 2. Pour chaque episode :
        #    a. mv storage source -> destination
        #    b. supprimer ancien symlink
        #    c. creer nouveau symlink
        #    d. update DB (file_path, symlink_path, title, series_id)
        for ep, new_file, new_sym in moves:
            old_file = Path(ep.file_path) if ep.file_path else None
            old_sym = Path(ep.symlink_path) if ep.symlink_path else None

            # Move storage
            if old_file and old_file.exists():
                if old_file != new_file:
                    shutil.move(str(old_file), str(new_file))
                    print(f"  [mv] {old_file.name} -> {new_file.name}")
            else:
                print(f"  [!] storage manquant : {old_file}")

            # Recreate symlink
            if old_sym and old_sym.is_symlink():
                old_sym.unlink()
            if not new_sym.exists() or new_sym.is_symlink():
                if new_sym.is_symlink():
                    new_sym.unlink()
                new_sym.symlink_to(new_file)
                print(f"  [ln] {new_sym}")

            # Update DB
            ep.series_id = 1069
            ep.file_path = str(new_file)
            ep.symlink_path = str(new_sym)
            # Titre canonique
            episode_label = (ep.season_number - 1) * 6 + ep.episode_number
            ep.title = f"Épisode {episode_label}"
            session.add(ep)

        session.commit()
        print("\n  [db] 12 episodes migres vers series_id=1069 + file_path/symlink_path/title mis a jour")

        # 3. Supprimer SeriesModel id=1067 et id=1068
        for sid in (1067, 1068):
            s = session.get(SeriesModel, sid)
            if s:
                session.delete(s)
                print(f"  [db] SeriesModel id={sid} supprimee")
        session.commit()

        # 4. Nettoyer les anciens dossiers (s'ils sont vides)
        for old_dir in (
            STORAGE_ROOT / "FLASHBACK (2014)",
            STORAGE_ROOT / "Flashback (2011)",
            STORAGE_ROOT / "Flashback (2025) (2025)",
            VIDEO_ROOT / "FLASHBACK (2014)",
            VIDEO_ROOT / "Flashback (2011)",
            VIDEO_ROOT / "Flashback (2025) (2025)",
        ):
            if not old_dir.exists():
                continue
            # Supprimer recursif si vide (fichiers cachés inclus)
            try:
                # Supprimer sous-dossiers vides d'abord
                for sub in sorted(old_dir.rglob("*"), key=lambda p: -len(p.parts)):
                    if sub.is_dir() and not any(sub.iterdir()):
                        sub.rmdir()
                if old_dir.is_dir() and not any(old_dir.iterdir()):
                    old_dir.rmdir()
                    print(f"  [rm] {old_dir}")
                else:
                    print(f"  [skip] {old_dir} non vide, conserve")
            except OSError as e:
                print(f"  [!] {old_dir} : {e}")

        print("\n[OK] Consolidation terminee.")
        return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    raise SystemExit(main(apply))
