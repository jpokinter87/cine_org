"""
Consolidation Shameless (US 2011) : fusionne les 134 épisodes éclatés sur 2 fiches
DB en une seule, déplace les fichiers vers un dossier unique et corrige les titres
d'épisodes via TVDB.

Avant :
  - id=1061 : 114 ep sous Shameless (2004)/Saison XX/  (titres FR de Shameless UK
              injectés à tort)
  - id=1062 : 20 ep  sous Shameless (US) (2011)/Saison XX/  (titres FR US OK)

Après :
  - id=1061 : 134 ep sous Shameless (2011)/Saison XX/ avec :
      * tmdb=34307, imdb=tt1586680, tvdb=161511, year=2011, title='Shameless'
      * titres d'épisodes officiels TVDB US (FR avec fallback EN)
  - id=1062 supprimée
  - Anciens dossiers Shameless (2004)/ et Shameless (US) (2011)/ supprimés

Usage :
  uv run python scripts/consolidate_shameless_us.py            # dry-run
  uv run python scripts/consolidate_shameless_us.py --apply    # exécution
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

from sqlmodel import Session, create_engine, select

from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.config import Settings
from src.container import Container
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


STORAGE_ROOT = Path("/media/NAS64/Series/TV/S/Sa-So/Sa-Sh")
VIDEO_ROOT = Path("/media/Serveur/Collection/Series/TV/S/Sa-So/Sa-Sh")
TARGET_DIRNAME = "Shameless (2011)"
TARGET_PREFIX = "Shameless (2011)"
TVDB_US_ID = "161511"
TMDB_US_ID = "34307"
KEEP_SERIES_ID = 1061
DROP_SERIES_ID = 1062

# Format CineOrg : "<Title> - SXXEYY - <Episode title> - <tech>.mkv"
# Tech part = ce qui reste apres le dernier " - " avant ".mkv"


def extract_tech_suffix(filename: str) -> str:
    """Recupere la partie 'FR x265 1080p' (ou variante) en fin de nom."""
    stem = filename.rsplit(".", 1)[0]
    return stem.rsplit(" - ", 1)[-1]


def sanitize_filename_component(text: str) -> str:
    """Nettoie un titre pour une utilisation sans danger en nom de fichier."""
    return text.replace("/", "-").replace("\\", "-").replace(":", " -").strip()


async def fetch_episode_titles(tvdb_client) -> dict[tuple[int, int], str]:
    """Recupere les titres d'episodes TVDB US (FR, fallback EN) pour toutes les
    saisons concernees."""
    titles: dict[tuple[int, int], str] = {}
    expected_per_season = {1: 12, 2: 12, 3: 12, 4: 12, 5: 12, 6: 12, 7: 12, 8: 12, 9: 14, 10: 12, 11: 12}
    for season, count in expected_per_season.items():
        for ep in range(1, count + 1):
            ed = await tvdb_client.get_episode_details(TVDB_US_ID, season, ep)
            t = ed.title if ed and ed.title else f"Episode {ep}"
            titles[(season, ep)] = t
    return titles


def main(apply: bool) -> int:
    engine = create_engine(Settings().database_url)
    moves: list[tuple[EpisodeModel, Path, Path, str]] = []  # (ep, new_file, new_sym, new_title)

    # 1. Telecharger les titres officiels TVDB US
    print("[…] Recuperation des titres TVDB Shameless US...")
    c = Container()
    tvdb = c.tvdb_client()
    titles = asyncio.run(fetch_episode_titles(tvdb))
    print(f"   {len(titles)} titres recuperes")

    with Session(engine) as session:
        # Charger tous les episodes concernes
        all_eps: list[EpisodeModel] = []
        for sid in (KEEP_SERIES_ID, DROP_SERIES_ID):
            all_eps.extend(
                session.exec(select(EpisodeModel).where(EpisodeModel.series_id == sid)).all()
            )

        # Verifier integrite : pas de doublons (saison, episode)
        seen: set[tuple[int, int]] = set()
        for e in all_eps:
            key = (e.season_number, e.episode_number)
            if key in seen:
                print(f"[!] Doublon detecte : S{key[0]:02d}E{key[1]:02d} apparait 2 fois en DB. Abandon.")
                return 1
            seen.add(key)

        print(f"\n=== Plan de consolidation ({'APPLY' if apply else 'DRY-RUN'}) ===")
        print(f"   {len(all_eps)} episodes a consolider\n")

        for ep in sorted(all_eps, key=lambda e: (e.season_number, e.episode_number)):
            old_file = Path(ep.file_path) if ep.file_path else None
            tech = extract_tech_suffix(old_file.name) if old_file else "FR x265 1080p"
            new_title = titles.get((ep.season_number, ep.episode_number), ep.title or "")
            new_filename = (
                f"{TARGET_PREFIX} - S{ep.season_number:02d}E{ep.episode_number:02d}"
                f" - {sanitize_filename_component(new_title)} - {tech}.mkv"
            )
            new_file = STORAGE_ROOT / TARGET_DIRNAME / f"Saison {ep.season_number:02d}" / new_filename
            new_sym = VIDEO_ROOT / TARGET_DIRNAME / f"Saison {ep.season_number:02d}" / new_filename
            moves.append((ep, new_file, new_sym, new_title))

        # Affichage condensé
        for ep, new_file, _, new_title in moves[:5]:
            print(f"  S{ep.season_number:02d}E{ep.episode_number:02d} (series_id={ep.series_id}) -> title={new_title!r}")
            print(f"    {ep.file_path}")
            print(f" -> {new_file}")
        print(f"  ... +{len(moves) - 5} autres moves (meme pattern)")

        if not apply:
            print("\n[dry-run] Aucune modification. Relancer avec --apply pour executer.")
            return 0

        # === APPLY ===
        print("\n=== Application ===")

        # 2. Creer dossiers cibles
        for season in sorted({e.season_number for e in all_eps}):
            (STORAGE_ROOT / TARGET_DIRNAME / f"Saison {season:02d}").mkdir(parents=True, exist_ok=True)
            (VIDEO_ROOT / TARGET_DIRNAME / f"Saison {season:02d}").mkdir(parents=True, exist_ok=True)

        # 3. Move + relink + DB update
        for ep, new_file, new_sym, new_title in moves:
            old_file = Path(ep.file_path) if ep.file_path else None
            old_sym = Path(ep.symlink_path) if ep.symlink_path else None

            if old_file and old_file.exists():
                if old_file != new_file:
                    shutil.move(str(old_file), str(new_file))
            else:
                print(f"  [!] storage manquant : {old_file}")

            if old_sym and old_sym.is_symlink():
                old_sym.unlink()
            if new_sym.is_symlink():
                new_sym.unlink()
            new_sym.symlink_to(new_file)

            ep.series_id = KEEP_SERIES_ID
            ep.file_path = str(new_file)
            ep.symlink_path = str(new_sym)
            ep.title = new_title
            session.add(ep)

        session.commit()
        print(f"  [db] {len(moves)} episodes consolides")

        # 4. Mise a jour SeriesModel id=1061 -> Shameless US
        print("  [api] Recuperation details TMDB Shameless US...")
        tmdb = c.tmdb_client()
        details, ext = asyncio.run(_fetch_tmdb_details(tmdb))
        s = session.get(SeriesModel, KEEP_SERIES_ID)
        s.title = "Shameless"
        s.original_title = details.original_title or "Shameless"
        s.year = 2011
        s.tmdb_id = int(TMDB_US_ID)
        s.imdb_id = ext.get("imdb_id") if ext else None
        s.tvdb_id = int(TVDB_US_ID)
        s.poster_path = details.poster_url
        s.overview = details.overview
        s.director = details.director
        s.cast_json = json.dumps(list(details.cast)) if details.cast else None
        s.genres_json = json.dumps(list(details.genres)) if details.genres else None
        s.vote_average = details.vote_average
        s.vote_count = details.vote_count

        # imdb_rating depuis cache local
        s.imdb_rating = None
        s.imdb_votes = None
        if s.imdb_id:
            importer = IMDbDatasetImporter(cache_dir=Path(".cache/imdb"), session=session)
            r = importer.get_rating(s.imdb_id)
            if r:
                s.imdb_rating, s.imdb_votes = r
        session.add(s)
        print(f"  [db] id={KEEP_SERIES_ID} : title='Shameless' year=2011 tmdb={s.tmdb_id} imdb={s.imdb_id} vote={s.vote_average} imdb_r={s.imdb_rating}")

        # 5. Supprimer id=1062
        drop = session.get(SeriesModel, DROP_SERIES_ID)
        if drop:
            session.delete(drop)
            print(f"  [db] SeriesModel id={DROP_SERIES_ID} supprimee")

        session.commit()

        # 6. Nettoyer anciens dossiers
        for old_dir in (
            STORAGE_ROOT / "Shameless (2004)",
            STORAGE_ROOT / "Shameless (US) (2011)",
            VIDEO_ROOT / "Shameless (2004)",
            VIDEO_ROOT / "Shameless (US) (2011)",
        ):
            if not old_dir.exists():
                continue
            try:
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

        print("\n[OK] Consolidation Shameless US terminee.")
        return 0


async def _fetch_tmdb_details(tmdb_client):
    d = await tmdb_client.get_tv_details(TMDB_US_ID)
    e = await tmdb_client.get_tv_external_ids(TMDB_US_ID)
    await tmdb_client.close()
    return d, e


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    raise SystemExit(main(apply))
