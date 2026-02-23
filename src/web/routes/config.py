"""
Route de la page de configuration.

Affiche et permet de modifier les paramètres de l'application (répertoires, clés API,
seuils de traitement, logging) via le fichier .env.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ...config import Settings, _ENV_FILE
from ..deps import templates

router = APIRouter()

# Champs éditables groupés par section
_SECTIONS = [
    {
        "id": "paths",
        "title": "Répertoires",
        "icon": "folder",
        "fields": [
            {"key": "downloads_dir", "label": "Téléchargements", "desc": "Dossier scanné pour les nouveaux fichiers", "type": "path"},
            {"key": "storage_dir", "label": "Stockage", "desc": "Zone physique de stockage des fichiers organisés", "type": "path"},
            {"key": "video_dir", "label": "Vidéo", "desc": "Zone de symlinks pour le médiacenter", "type": "path"},
        ],
    },
    {
        "id": "database",
        "title": "Base de données",
        "icon": "database",
        "fields": [
            {"key": "database_url", "label": "URL de la base", "desc": "Connexion SQLite (lecture seule)", "type": "readonly"},
        ],
    },
    {
        "id": "api",
        "title": "Clés API",
        "icon": "key",
        "fields": [
            {"key": "tmdb_api_key", "label": "TMDB", "desc": "The Movie Database — films et séries", "type": "secret"},
            {"key": "tvdb_api_key", "label": "TVDB", "desc": "TheTVDB — séries TV", "type": "secret"},
        ],
    },
    {
        "id": "processing",
        "title": "Traitement",
        "icon": "sliders",
        "fields": [
            {"key": "min_file_size_mb", "label": "Taille min. fichier (Mo)", "desc": "Ignorer les fichiers plus petits", "type": "number", "min": 1, "max": 10000},
            {"key": "max_files_per_subdir", "label": "Max fichiers / sous-dossier", "desc": "Seuil de subdivision alphabétique", "type": "number", "min": 1, "max": 500},
            {"key": "match_score_threshold", "label": "Seuil de validation auto (%)", "desc": "Score minimum pour validation automatique", "type": "number", "min": 0, "max": 100},
        ],
    },
    {
        "id": "logging",
        "title": "Journalisation",
        "icon": "file-text",
        "fields": [
            {"key": "log_level", "label": "Niveau de log", "desc": "Verbosité des journaux", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
            {"key": "log_file", "label": "Fichier de log", "desc": "Chemin du fichier journal", "type": "text"},
            {"key": "log_rotation_size", "label": "Taille rotation", "desc": "Taille maximale avant rotation", "type": "text"},
            {"key": "log_retention_count", "label": "Rétention", "desc": "Nombre de fichiers de log conservés", "type": "number", "min": 1, "max": 100},
        ],
    },
]

# Mapping des clés .env vers les clés Settings
_ENV_PREFIX = "CINEORG_"


def _mask_secret(value: str | None) -> str:
    """Masque une clé API en ne montrant que les 4 derniers caractères."""
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def _get_path_status(path: Path) -> dict:
    """Vérifie l'existence d'un répertoire et retourne le statut."""
    exists = path.exists()
    is_dir = path.is_dir() if exists else False
    return {"exists": exists, "is_dir": is_dir}


def _build_field_data(settings: Settings) -> list[dict]:
    """Construit les données des sections avec valeurs actuelles et statuts."""
    sections = []
    for section in _SECTIONS:
        section_data = {**section, "fields": []}
        for field in section["fields"]:
            value = getattr(settings, field["key"], "")
            field_data = {**field, "value": str(value) if value is not None else ""}

            if field["type"] == "path":
                path = Path(str(value)) if value else Path()
                field_data["status"] = _get_path_status(path)

            if field["type"] == "secret":
                field_data["masked"] = _mask_secret(str(value) if value else None)
                field_data["is_set"] = value is not None and str(value).strip() != ""

            section_data["fields"].append(field_data)
        sections.append(section_data)
    return sections


def _read_env_lines() -> list[str]:
    """Lit le fichier .env et retourne les lignes."""
    if _ENV_FILE.exists():
        return _ENV_FILE.read_text(encoding="utf-8").splitlines()
    return []


def _write_env(updates: dict[str, str]) -> None:
    """Met à jour le fichier .env en préservant commentaires et structure."""
    lines = _read_env_lines()
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Ligne de type KEY=VALUE
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                env_key = key.replace(_ENV_PREFIX, "").lower() if key.startswith(_ENV_PREFIX) else None
                if env_key and env_key in updates:
                    new_lines.append(f"{key}={updates[env_key]}")
                    updated_keys.add(env_key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Ajouter les clés manquantes à la fin
    for key, value in updates.items():
        if key not in updated_keys:
            env_key = f"{_ENV_PREFIX}{key.upper()}"
            new_lines.append(f"{env_key}={value}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _validate_form(form_data: dict) -> dict[str, str]:
    """Valide les données du formulaire. Retourne un dict d'erreurs par champ."""
    errors = {}

    # Valider les champs numériques
    for key in ("min_file_size_mb", "max_files_per_subdir", "match_score_threshold", "log_retention_count"):
        if key in form_data and form_data[key].strip():
            try:
                val = int(form_data[key])
                if key == "min_file_size_mb" and val < 1:
                    errors[key] = "Doit être supérieur à 0"
                elif key == "max_files_per_subdir" and val < 1:
                    errors[key] = "Doit être supérieur à 0"
                elif key == "match_score_threshold" and (val < 0 or val > 100):
                    errors[key] = "Doit être entre 0 et 100"
                elif key == "log_retention_count" and val < 1:
                    errors[key] = "Doit être supérieur à 0"
            except ValueError:
                errors[key] = "Valeur numérique attendue"

    # Valider les chemins non vides
    for key in ("downloads_dir", "storage_dir", "video_dir"):
        if key in form_data and not form_data[key].strip():
            errors[key] = "Le chemin ne peut pas être vide"

    return errors


@router.get("/config")
async def config_page(request: Request, saved: int = 0):
    """Affiche la page de configuration."""
    settings = Settings()
    sections = _build_field_data(settings)

    return templates.TemplateResponse(
        request,
        "config/index.html",
        {
            "sections": sections,
            "saved": saved == 1,
        },
    )


@router.post("/config")
async def config_save(request: Request):
    """Sauvegarde les paramètres modifiés dans le fichier .env."""
    form = await request.form()
    form_data = dict(form)

    # Valider
    errors = _validate_form(form_data)
    if errors:
        settings = Settings()
        sections = _build_field_data(settings)
        return templates.TemplateResponse(
            request,
            "config/index.html",
            {
                "sections": sections,
                "saved": False,
                "errors": errors,
                "form_data": form_data,
            },
        )

    # Construire les mises à jour (ignorer les clés API non modifiées)
    updates = {}
    editable_keys = set()
    for section in _SECTIONS:
        for field in section["fields"]:
            if field["type"] != "readonly":
                editable_keys.add(field["key"])

    for key in editable_keys:
        if key not in form_data:
            continue
        value = form_data[key].strip()

        # Pour les secrets : si la valeur commence par "••••", l'utilisateur n'a pas modifié
        if key in ("tmdb_api_key", "tvdb_api_key"):
            if value.startswith("••••") or value == "":
                continue

        updates[key] = value

    if updates:
        _write_env(updates)

    return RedirectResponse(url="/config?saved=1", status_code=303)
