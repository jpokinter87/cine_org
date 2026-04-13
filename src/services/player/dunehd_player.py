"""
Backend lecteur DuneHD : envoie un ordre de lecture HTTP à un media player
Dune HD via son API `/cgi-bin/do?cmd=start_file_playback`.

Le fichier local (dans storage/Films/... ou storage/Séries/...) est traduit en
URL SMB pointant vers le partage exporté par le serveur de fichiers. Le Dune
lit ensuite directement l'URL SMB sur le réseau local.

Limitations connues de l'API Dune :
- pas de reprise de lecture (le Dune n'enregistre pas la position via cet endpoint)
- pas d'intégration dans l'historique "en cours" du Dune
- télécommande Dune fonctionnelle (pause/stop/skip)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from loguru import logger


@dataclass(frozen=True)
class DuneHDResult:
    """Résultat d'une commande HTTP Dune."""

    ok: bool
    player_state: Optional[str]
    error: Optional[str]


class DuneHDMappingError(ValueError):
    """Levée quand un chemin local ne peut pas être traduit en URL SMB."""


def map_to_smb(local_path: Path, profile: dict) -> str:
    """Traduit un chemin local vers une URL SMB selon le profil DuneHD.

    Détecte automatiquement si le chemin concerne un film ou une série via le
    segment `Films` ou `Séries` (ou `Series` pour la variante anglaise). Remplace
    la portion locale par le préfixe SMB correspondant.

    Retourne l'URL SMB brute (non-encodée) — httpx se charge de l'encoding
    lorsqu'elle est passée via `params=`.
    """
    path_str = str(local_path).replace("\\", "/")

    movies_prefix = profile.get("smb_movies_prefix")
    series_prefix = profile.get("smb_series_prefix")

    # On cherche le premier marqueur de type dans le chemin
    for marker, prefix in (
        ("/Films/", movies_prefix),
        ("/Séries/", series_prefix),
        ("/Series/", series_prefix),
    ):
        idx = path_str.find(marker)
        if idx >= 0:
            if not prefix:
                raise DuneHDMappingError(
                    f"Préfixe SMB manquant pour le type détecté via {marker.strip('/')}"
                )
            suffix = path_str[idx + len(marker):]
            return f"{prefix.rstrip('/')}/{suffix}"

    raise DuneHDMappingError(
        f"Chemin non reconnu (ni Films/ ni Séries/) : {local_path}"
    )


def _parse_dune_xml(xml_text: str) -> DuneHDResult:
    """Parse la réponse XML du Dune et extrait les champs clés."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return DuneHDResult(ok=False, player_state=None, error=f"XML invalide : {exc}")

    params = {
        p.get("name"): p.get("value")
        for p in root.findall("param")
    }
    status = params.get("command_status")
    if status == "ok":
        return DuneHDResult(
            ok=True,
            player_state=params.get("player_state"),
            error=None,
        )
    return DuneHDResult(
        ok=False,
        player_state=params.get("player_state"),
        error=params.get("error_description") or f"command_status={status}",
    )


class DuneHDPlayer:
    """Client HTTP léger pour piloter un Dune HD via start_file_playback."""

    def __init__(self, profile: dict, timeout: float = 5.0) -> None:
        if profile.get("type") != "dunehd":
            raise ValueError(
                f"DuneHDPlayer requiert un profil type='dunehd', reçu : {profile.get('type')}"
            )
        if not profile.get("ip"):
            raise ValueError("Profil DuneHD sans IP configurée")
        self.profile = profile
        self.timeout = timeout

    def play(self, file_path: Path) -> DuneHDResult:
        """Envoie au Dune l'ordre de lire le fichier donné.

        Retourne un DuneHDResult (ok=True si le Dune a accepté la commande).
        Log loguru : info au lancement, warning si l'API répond en erreur,
        error si le réseau échoue (timeout, DNS, refus).
        """
        try:
            smb_url = map_to_smb(file_path, self.profile)
        except DuneHDMappingError as exc:
            logger.warning(f"Mapping SMB impossible pour {file_path} : {exc}")
            return DuneHDResult(ok=False, player_state=None, error=str(exc))

        url = f"http://{self.profile['ip']}/cgi-bin/do"
        params = {"cmd": "start_file_playback", "media_url": smb_url}
        logger.info(
            f"DuneHD play → {self.profile.get('name', '?')} ({self.profile['ip']}) : {smb_url}"
        )

        try:
            response = httpx.get(url, params=params, timeout=self.timeout)
        except httpx.TimeoutException:
            msg = f"Timeout (>{self.timeout}s) lors de l'appel au Dune {self.profile['ip']}"
            logger.error(msg)
            return DuneHDResult(ok=False, player_state=None, error=msg)
        except httpx.HTTPError as exc:
            msg = f"Erreur réseau Dune {self.profile['ip']} : {exc}"
            logger.error(msg)
            return DuneHDResult(ok=False, player_state=None, error=msg)

        if response.status_code != 200:
            msg = f"Dune HTTP {response.status_code}"
            logger.warning(msg)
            return DuneHDResult(ok=False, player_state=None, error=msg)

        result = _parse_dune_xml(response.text)
        if not result.ok:
            logger.warning(
                f"DuneHD a refusé la commande : {result.error} (state={result.player_state})"
            )
        return result
