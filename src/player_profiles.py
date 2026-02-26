"""
Gestion des profils lecteur vidéo — stockage JSON, CRUD, profil actif.

Les profils permettent de basculer rapidement entre machines cibles
(local, Xubuntu salon, Windows bureau, etc.) sans modifier la config .env.
"""

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_PROFILES_FILE = _PROJECT_ROOT / "player_profiles.json"

_DEFAULT_PROFILE = {
    "name": "Local",
    "command": "mpv",
    "target": "local",
    "ssh_host": None,
    "ssh_user": None,
    "local_path_prefix": None,
    "remote_path_prefix": None,
}

_PROFILE_FIELDS = (
    "name", "command", "target", "ssh_host", "ssh_user",
    "local_path_prefix", "remote_path_prefix",
)


def _ensure_profile(profile: dict) -> dict:
    """Complète un profil avec les valeurs par défaut manquantes."""
    result = dict(_DEFAULT_PROFILE)
    result.update({k: v for k, v in profile.items() if k in _PROFILE_FIELDS})
    return result


def _migrate_from_env() -> dict | None:
    """Tente de créer un profil à partir des anciens champs player_* du .env."""
    env_file = _PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None
    env_values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, val = stripped.split("=", 1)
            env_values[key.strip().upper()] = val.strip()

    # Vérifier s'il y a des champs player_* dans le .env
    mapping = {
        "CINEORG_PLAYER_COMMAND": "command",
        "CINEORG_PLAYER_TARGET": "target",
        "CINEORG_PLAYER_SSH_HOST": "ssh_host",
        "CINEORG_PLAYER_SSH_USER": "ssh_user",
        "CINEORG_PLAYER_LOCAL_PATH_PREFIX": "local_path_prefix",
        "CINEORG_PLAYER_REMOTE_PATH_PREFIX": "remote_path_prefix",
    }
    profile = {"name": "Migré"}
    found = False
    for env_key, field in mapping.items():
        if env_key in env_values and env_values[env_key]:
            profile[field] = env_values[env_key]
            found = True

    return _ensure_profile(profile) if found else None


def load_profiles() -> dict:
    """Charge les profils depuis le JSON. Crée le fichier par défaut si absent."""
    if _PROFILES_FILE.exists():
        try:
            data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
            if "profiles" in data and data["profiles"]:
                return data
        except (json.JSONDecodeError, KeyError):
            pass

    # Fichier absent ou invalide — créer avec le profil par défaut
    profiles = [dict(_DEFAULT_PROFILE)]

    # Migration depuis les anciens champs .env
    migrated = _migrate_from_env()
    if migrated and migrated.get("target") == "remote":
        profiles.append(migrated)
        active = migrated["name"]
    else:
        active = "Local"

    data = {"active": active, "profiles": profiles}
    save_profiles(data)
    return data


def save_profiles(data: dict) -> None:
    """Écrit les profils dans le fichier JSON."""
    _PROFILES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get_active_profile() -> dict:
    """Retourne le profil actif (ou le défaut local)."""
    data = load_profiles()
    active_name = data.get("active", "Local")
    for p in data.get("profiles", []):
        if p["name"] == active_name:
            return _ensure_profile(p)
    # Profil actif introuvable — fallback
    if data.get("profiles"):
        return _ensure_profile(data["profiles"][0])
    return dict(_DEFAULT_PROFILE)


def set_active_profile(name: str) -> None:
    """Change le profil actif."""
    data = load_profiles()
    names = [p["name"] for p in data.get("profiles", [])]
    if name in names:
        data["active"] = name
        save_profiles(data)


def add_profile(profile: dict) -> None:
    """Ajoute un nouveau profil."""
    data = load_profiles()
    profile = _ensure_profile(profile)
    # Éviter les doublons de nom
    existing_names = {p["name"] for p in data["profiles"]}
    if profile["name"] in existing_names:
        return
    data["profiles"].append(profile)
    save_profiles(data)


def update_profile(name: str, profile: dict) -> None:
    """Met à jour un profil existant."""
    data = load_profiles()
    for i, p in enumerate(data["profiles"]):
        if p["name"] == name:
            updated = _ensure_profile(profile)
            data["profiles"][i] = updated
            # Si le profil actif a été renommé, mettre à jour
            if data["active"] == name and updated["name"] != name:
                data["active"] = updated["name"]
            save_profiles(data)
            return


def delete_profile(name: str) -> bool:
    """Supprime un profil. Retourne False si c'est le profil 'Local' (protégé)."""
    if name == "Local":
        return False
    data = load_profiles()
    data["profiles"] = [p for p in data["profiles"] if p["name"] != name]
    if data["active"] == name:
        data["active"] = "Local"
    save_profiles(data)
    return True
