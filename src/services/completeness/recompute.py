"""Recalcul de la complétude des séries touchées par un transfert.

Appelé en fin de transfert (CLI et web) pour que le verdict de complétude
(``completeness_status`` + flags) soit à jour dès qu'une série est complétée,
sans action manuelle. ``check_series_model`` écrasant intégralement le verdict,
aucun reset préalable n'est nécessaire.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from loguru import logger

from src.infrastructure.persistence.models import SeriesModel
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)


async def recompute_completeness_for_series(
    session,
    tvdb_client,
    series_ids: Iterable[int],
    today: Optional[date] = None,
) -> int:
    """Recalcule la complétude des séries dont l'id est fourni.

    Dédoublonne les series_id (une série reçoit souvent plusieurs épisodes dans
    un batch ; ``get_all_episodes`` n'est pas caché). Chaque série est isolée par
    un try/except : un échec TVDB (réseau/quota) n'interrompt pas les autres et
    ne remonte pas — le transfert est déjà réussi.

    Returns:
        Le nombre de séries effectivement recalculées.
    """
    unique = {sid for sid in series_ids if sid is not None}
    if not unique:
        return 0

    checker = CompletenessChecker(tvdb_client)
    today = today or date.today()
    count = 0
    for sid in unique:
        series = session.get(SeriesModel, sid)
        if series is None:
            continue
        try:
            await check_series_model(session, checker, series, today)
            count += 1
        except Exception as e:
            logger.warning(f"Recalcul complétude échoué pour série {sid}: {e}")
    return count
