"""Boucle de surveillance du partage : démontage auto (idle 30 min, plafond 6 h)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

_INTERVAL_SECONDS = 60


async def run_one_cycle(container) -> None:
    """Un tick de surveillance (isolé pour testabilité). N'élève jamais."""
    try:
        service = container.share_service()
        result = await service.run_monitor_tick(datetime.utcnow())
        if result == "idle":
            logger.info("Partage démonté automatiquement (30 min sans lecture).")
        elif result == "hard_cap":
            logger.info("Partage démonté automatiquement (plafond de 6 h atteint).")
    except Exception as exc:  # surveillance ne doit jamais tuer la boucle
        logger.exception("Erreur dans le cycle de surveillance du partage : %s", exc)


async def share_monitor_loop(container) -> None:
    """Auto-réparation au démarrage puis boucle périodique jusqu'à annulation."""
    try:
        await container.share_service().reconcile_on_startup()
    except Exception as exc:
        logger.exception("Échec de l'auto-réparation au démarrage : %s", exc)
    while True:
        await run_one_cycle(container)
        await asyncio.sleep(_INTERVAL_SECONDS)
