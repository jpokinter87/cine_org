"""
Helpers pour la gestion des overrides de metadonnees manuels (phase 42-02).

Gere le stockage des affiches uploadees ou telechargees dans le repertoire
`storage/.metadata/posters/` avec convention de nommage
`{entity_type}-{entity_id}{ext}`.

Les champs texte (overview, cast) sont persistes dans les colonnes DB
(`overview_override`, `cast_override_json`) ; ce module ne gere que les
fichiers binaires (affiches).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

import httpx
from loguru import logger


EntityType = Literal["movie", "series"]

ALLOWED_POSTER_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp"}
)

CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def get_metadata_dir(storage_dir: Path) -> Path:
    """
    Retourne le repertoire `storage/.metadata/posters/`, en le creant si besoin.

    Args:
        storage_dir: Racine du volume storage

    Returns:
        Path absolu du repertoire posters
    """
    posters_dir = storage_dir / ".metadata" / "posters"
    posters_dir.mkdir(parents=True, exist_ok=True)
    return posters_dir


def poster_filename(entity_type: EntityType, entity_id: int, ext: str) -> str:
    """
    Retourne le nom de fichier standardise : `{type}-{id}{ext}`.

    Args:
        entity_type: "movie" ou "series"
        entity_id: ID interne DB
        ext: Extension avec le point (ex: ".jpg")

    Returns:
        Nom de fichier (sans chemin)
    """
    ext_normalized = ext.lower()
    if not ext_normalized.startswith("."):
        ext_normalized = "." + ext_normalized
    return f"{entity_type}-{entity_id}{ext_normalized}"


def _cleanup_previous_posters(
    posters_dir: Path, entity_type: EntityType, entity_id: int, keep: Path
) -> None:
    """Supprime les posters precedents de l'entite (extensions differentes)."""
    prefix = f"{entity_type}-{entity_id}."
    for p in posters_dir.iterdir():
        if p.name.startswith(prefix) and p != keep:
            try:
                p.unlink()
            except OSError as exc:
                logger.debug("Impossible de supprimer %s : %s", p, exc)


def save_poster_upload(
    storage_dir: Path,
    entity_type: EntityType,
    entity_id: int,
    upload_filename: str,
    content: bytes,
) -> Path:
    """
    Sauvegarde un fichier image uploade dans `.metadata/posters/`.

    Args:
        storage_dir: Racine du storage
        entity_type: "movie" ou "series"
        entity_id: ID de l'entite
        upload_filename: Nom d'origine (utilise pour determiner l'extension)
        content: Contenu binaire

    Returns:
        Path absolu du fichier ecrit

    Raises:
        ValueError: Si l'extension n'est pas autorisee
    """
    ext = Path(upload_filename).suffix.lower()
    if ext not in ALLOWED_POSTER_EXTENSIONS:
        raise ValueError(
            f"Extension {ext!r} non autorisee. "
            f"Formats acceptes : {sorted(ALLOWED_POSTER_EXTENSIONS)}"
        )

    posters_dir = get_metadata_dir(storage_dir)
    target = posters_dir / poster_filename(entity_type, entity_id, ext)
    target.write_bytes(content)

    _cleanup_previous_posters(posters_dir, entity_type, entity_id, keep=target)
    return target


def _extension_from_response(
    response: httpx.Response, url: str
) -> Optional[str]:
    """Deduit l'extension depuis Content-Type ou l'URL."""
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in CONTENT_TYPE_TO_EXT:
        return CONTENT_TYPE_TO_EXT[content_type]

    # Fallback : extension de l'URL
    url_ext = Path(httpx.URL(url).path).suffix.lower()
    if url_ext in ALLOWED_POSTER_EXTENSIONS:
        return url_ext
    return None


def save_poster_from_url(
    storage_dir: Path,
    entity_type: EntityType,
    entity_id: int,
    url: str,
    http_client: Optional[httpx.Client] = None,
) -> Path:
    """
    Telecharge une image depuis une URL et la sauvegarde localement.

    Args:
        storage_dir: Racine du storage
        entity_type: "movie" ou "series"
        entity_id: ID de l'entite
        url: URL HTTP(S) pointant sur une image
        http_client: Client httpx optionnel (pour tests)

    Returns:
        Path absolu du fichier ecrit

    Raises:
        ValueError: Si le statut n'est pas 200, le Content-Type n'est pas
            image, ou aucune extension ne peut etre determinee.
    """
    if not re.match(r"^https?://", url):
        raise ValueError(f"URL invalide : {url!r}")

    client = http_client if http_client is not None else httpx.Client(timeout=10.0)
    try:
        response = client.get(url, follow_redirects=True)
    finally:
        if http_client is None:
            client.close()

    if response.status_code != 200:
        raise ValueError(
            f"Telechargement echec (status {response.status_code}) pour {url!r}"
        )

    content_type = response.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        raise ValueError(
            f"Content-Type invalide pour une image : {content_type!r}"
        )

    ext = _extension_from_response(response, url)
    if ext is None:
        raise ValueError(
            f"Extension d'image introuvable pour Content-Type {content_type!r} "
            f"et URL {url!r}"
        )

    posters_dir = get_metadata_dir(storage_dir)
    target = posters_dir / poster_filename(entity_type, entity_id, ext)
    target.write_bytes(response.content)

    _cleanup_previous_posters(posters_dir, entity_type, entity_id, keep=target)
    return target


def delete_poster(
    storage_dir: Path, entity_type: EntityType, entity_id: int
) -> bool:
    """
    Supprime tous les fichiers poster de l'entite (toutes extensions).

    Args:
        storage_dir: Racine du storage
        entity_type: "movie" ou "series"
        entity_id: ID de l'entite

    Returns:
        True si au moins un fichier a ete supprime
    """
    posters_dir = get_metadata_dir(storage_dir)
    prefix = f"{entity_type}-{entity_id}."
    deleted = False
    for p in posters_dir.iterdir():
        if p.name.startswith(prefix):
            try:
                p.unlink()
                deleted = True
            except OSError as exc:
                logger.debug("Suppression %s echouee : %s", p, exc)
    return deleted


def find_poster(
    storage_dir: Path, entity_type: EntityType, entity_id: int
) -> Optional[Path]:
    """Retourne le chemin du poster si present pour l'entite."""
    posters_dir = get_metadata_dir(storage_dir)
    prefix = f"{entity_type}-{entity_id}."
    for p in posters_dir.iterdir():
        if p.name.startswith(prefix):
            return p
    return None
