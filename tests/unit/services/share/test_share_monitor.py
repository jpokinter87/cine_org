"""Tests de la boucle de surveillance du partage."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.share.monitor import run_one_cycle


@pytest.mark.asyncio
async def test_run_one_cycle_calls_tick_with_now():
    service = MagicMock()
    service.run_monitor_tick = AsyncMock(return_value=None)
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    await run_one_cycle(container)
    service.run_monitor_tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_one_cycle_swallows_errors():
    service = MagicMock()
    service.run_monitor_tick = AsyncMock(side_effect=RuntimeError("boom"))
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    # ne doit pas lever
    await run_one_cycle(container)
