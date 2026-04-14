"""
Script one-shot : annuler les validations Big C + override, pour retest.

Utilisation typique apres un test de la route /workflow/anomalies/accept
(phase 42-01) ou tous les pendings sont passes en VALIDATED (via le
fallback ou via auto-validation au 2e run) et ou l'override (161501, 4)
a ete persiste.

Effet :
- DELETE tous les pending_validations "The Big C" (tous statuts)
- DELETE les video_files associes
- DELETE l'override (tvdb_id=161501, season=4)

Ne touche PAS :
- Les fichiers physiques dans downloads (44 fichiers restent)
- Les EpisodeModel de la DB (ne sont pas creees tant que le transfert
  n'a pas lieu)

Apres execution, relancer le workflow : on retombe sur 40 auto-valides
/ 4 en attente, avec anomalie detectee sur The Big C S04.

Usage :
    uv run python -m scripts.reset_big_c_validations            # dry-run
    uv run python -m scripts.reset_big_c_validations --apply    # execution
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

from src.infrastructure.persistence.database import init_db, get_engine
from src.infrastructure.persistence.models import (
    PendingValidationModel,
    SeasonOverrideModel,
    VideoFileModel,
)


BIG_C_TVDB_ID = 161501
BIG_C_FILENAME_MARKER = "Big.C"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Execute (sinon dry-run)."
    )
    args = parser.parse_args()

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        # Pendings Big C (toutes statuts)
        pendings = session.exec(
            select(PendingValidationModel, VideoFileModel)
            .join(VideoFileModel, PendingValidationModel.video_file_id == VideoFileModel.id)
            .where(VideoFileModel.filename.like(f"%{BIG_C_FILENAME_MARKER}%"))
        ).all()

        # Override
        override = session.exec(
            select(SeasonOverrideModel).where(
                SeasonOverrideModel.tvdb_id == BIG_C_TVDB_ID,
                SeasonOverrideModel.season_number == 4,
            )
        ).first()

        print("=" * 60)
        print(f"[DB] {len(pendings)} pendings Big C à supprimer")
        by_status: dict[str, int] = {}
        for p, _ in pendings:
            by_status[p.validation_status] = by_status.get(p.validation_status, 0) + 1
        for status, n in by_status.items():
            print(f"    - {status}: {n}")

        print(f"[DB] {len(pendings)} video_files Big C à supprimer")
        print(f"[DB] override (161501, 4): {'présent' if override else 'absent'}")
        print("=" * 60)

        if not args.apply:
            print("DRY-RUN : aucune action. Relance avec --apply.")
            return 0

        for p, vf in pendings:
            session.delete(p)
            session.delete(vf)
        if override is not None:
            session.delete(override)
        session.commit()
        print(">>> APPLY termine.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
