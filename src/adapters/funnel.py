"""Contrôle du Tailscale Funnel (exposition publique à la demande) par sous-processus.

Tourne en utilisateur `jp` déclaré opérateur Tailscale → pas de sudo nécessaire.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

from loguru import logger


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


class SubprocessRunner:
    """Exécute réellement la commande (capture sortie, ne lève pas)."""

    def run(self, args: list[str]) -> CommandResult:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:  # binaire tailscale absent
            return CommandResult(returncode=127, stdout="", stderr=str(exc))
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


class FunnelController:
    def __init__(self, port: int = 8096, runner: CommandRunner | None = None) -> None:
        self._port = port
        self._runner = runner or SubprocessRunner()

    def enable(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "--bg", str(self._port)])
        if result.returncode != 0:
            logger.error("Échec activation Funnel : %s", result.stderr.strip())
            return False
        return True

    def disable(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "--https=443", "off"])
        if result.returncode != 0:
            logger.error("Échec coupure Funnel : %s", result.stderr.strip())
            return False
        return True

    def is_on(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "status"])
        return result.returncode == 0 and "Funnel on" in result.stdout
