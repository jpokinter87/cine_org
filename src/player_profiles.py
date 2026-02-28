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


def load_profiles() -> dict:
    """Charge les profils depuis le JSON. Crée le fichier par défaut si absent."""
    if _PROFILES_FILE.exists():
        try:
            data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
            if "profiles" in data and data["profiles"]:
                # Filtrer le profil "Migré" (vestige de l'ancienne migration .env)
                original_len = len(data["profiles"])
                data["profiles"] = [
                    p for p in data["profiles"] if p.get("name") != "Migré"
                ]
                if data.get("active") == "Migré":
                    data["active"] = "Local"
                # Persister le nettoyage si des profils ont été retirés
                if len(data["profiles"]) < original_len:
                    save_profiles(data)
                return data
        except (json.JSONDecodeError, KeyError):
            pass

    # Fichier absent ou invalide — créer avec le profil par défaut
    data = {"active": "Local", "profiles": [dict(_DEFAULT_PROFILE)]}
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


def get_profile_by_name(name: str) -> dict | None:
    """Retourne un profil par son nom, ou None si introuvable."""
    data = load_profiles()
    for p in data.get("profiles", []):
        if p["name"] == name:
            return _ensure_profile(p)
    return None


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
