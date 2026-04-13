---
phase: 40-lecteur-dunehd
plan: 01
subsystem: player
tags: [dunehd, smb, httpx, xml, media-playback, profiles]

requires:
  - phase: 16-lecteur-distant
    provides: profils lecteur JSON (mpv local/SSH) + _launch_player dispatcher
  - phase: 23-lectures-simultanees
    provides: popover sélection profil + polling /play-status

provides:
  - backend DuneHDPlayer (API HTTP /cgi-bin/do + mapping SMB + parsing XML)
  - schéma profil étendu (type, ip, smb_movies_prefix, smb_series_prefix)
  - dispatcher _launch_player avec branche dunehd
  - tests unitaires respx (15) + player_profiles (7) + intégration dispatcher (2)

affects: [40-02 (UI config), futurs backends lecteur (Chromecast, Plex Remote, etc.)]

tech-stack:
  added:
    - xml.etree.ElementTree (stdlib, parsing réponse Dune)
  patterns:
    - Backend lecteur pluggable via champ profile.type
    - Fire-and-forget pour lecteurs HTTP (pid synthétique >= 10M)
    - DuneHDResult dataclass frozen pour retours structurés
    - httpx params= au lieu de quote() manuel pour URL-encoding

key-files:
  created:
    - src/services/player/__init__.py
    - src/services/player/dunehd_player.py
    - tests/unit/test_player_profiles.py
    - tests/unit/test_dunehd_player.py
  modified:
    - src/player_profiles.py
    - src/web/routes/library/player.py
    - tests/unit/test_player.py

key-decisions:
  - "PID synthétique ≥ 10_000_000 pour distinguer les entrées DuneHD (fire-and-forget) des vrais processus Linux sans complexifier la structure _active_players"
  - "ElementTree stdlib pour parser la réponse Dune plate (<command_result><param .../>…), pas de dépendance supplémentaire"
  - "httpx params= laisse httpx gérer l'URL-encoding (espaces/parenthèses/accents), map_to_smb retourne l'URL brute"
  - "Mapping par marqueur /Films/ ou /Séries/ ou /Series/ dans le chemin (détection automatique film vs série, variante anglaise acceptée pour robustesse)"
  - "DuneHDResult frozen dataclass (ok, player_state, error) au lieu de tuple, lisible et auto-documenté"

patterns-established:
  - "src/services/player/ comme répertoire pour les backends lecteur (future home pour Chromecast, Plex Remote, etc.)"
  - "Dispatch par profile.type en tête de _launch_player, branches mpv existantes préservées telles quelles"
  - "_dunehd_errors dict parallèle à _active_players consommé par /play-status pour propager les erreurs API"

duration: ~25min
started: 2026-04-14T15:00:00Z
completed: 2026-04-14T15:25:00Z
---

# Phase 40 Plan 01: Backend DuneHD Player — Summary

**Backend DuneHD fonctionnel : appel HTTP `start_file_playback` + mapping SMB films/séries + dispatcher par type de profil, 38 tests verts, rétrocompatibilité mpv stricte.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~25min |
| Started | 2026-04-14T15:00:00Z |
| Completed | 2026-04-14T15:25:00Z |
| Tasks | 3/3 completed |
| Files modified | 7 (4 created, 3 modified) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1 Schéma profil rétrocompatible | ✅ Pass | `test_load_profiles_reads_legacy_file_without_type` : profil sans `type` reçoit `"mpv"` par défaut |
| AC-2 Profil DuneHD fonctionnel | ✅ Pass | `test_play_succes_command_status_ok` vérifie URL, params et XML parsing ; URL SMB correcte avec espaces/parenthèses |
| AC-3 Routage séries (accent local) | ✅ Pass | `test_map_to_smb_serie_avec_accent` : `/storage/Séries/...` → `smb://.../Series TV/...` |
| AC-4 Dispatch selon type | ✅ Pass | `test_dispatch_vers_dunehd_quand_type_dunehd` : DuneHDPlayer invoqué, subprocess.Popen pas appelé |
| AC-5 Gestion des erreurs API | ✅ Pass | Timeout, ConnectError, HTTP 500, `command_status=failed` tous couverts → `DuneHDResult(ok=False, error=...)` |

## Accomplishments

- **Nouveau backend lecteur DuneHD** pleinement fonctionnel depuis le dispatcher existant, sans refonte des routes `/library/{entity}/{id}/play` ni du popover UI — le type est détecté en amont et routé en transparence
- **Rétrocompatibilité profil stricte** : les 2 profils existants sur disque (Local + profils SSH utilisateur) continuent de fonctionner sans modification ni migration manuelle ; `_ensure_profile` complète silencieusement les nouveaux champs avec leurs défauts
- **Couverture test solide** : 38 tests unitaires (7 player_profiles, 15 dunehd_player, 16 player dont 2 nouveaux pour le dispatch), ruff clean sur tous les fichiers modifiés

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/player_profiles.py` | Modified | Ajout champs `type`/`ip`/`smb_movies_prefix`/`smb_series_prefix` au schéma, rétrocompat via `_ensure_profile` |
| `src/services/player/__init__.py` | Created | Nouveau package pour les backends lecteur |
| `src/services/player/dunehd_player.py` | Created | `map_to_smb()` + classe `DuneHDPlayer` + `DuneHDResult` dataclass |
| `src/web/routes/library/player.py` | Modified | `_launch_dunehd()`, dispatch `type=="dunehd"` dans `_launch_player`, gestion `proc=None` dans `/play-status` |
| `tests/unit/test_player_profiles.py` | Created | 7 tests schéma + roundtrip JSON |
| `tests/unit/test_dunehd_player.py` | Created | 15 tests : mapping SMB (films, séries, variante anglaise, espaces, erreurs) + API (succès, failed, timeout, connect error, HTTP 500) |
| `tests/unit/test_player.py` | Modified | +classe `TestLaunchPlayerDuneHD` (2 tests), suppression `import pytest` pré-existant inutilisé |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| PID synthétique ≥ 10_000_000 | Évite collision avec les vrais PIDs Linux (< 4M typiquement), pas de changement de structure `_active_players` | Dispatch transparent pour `/play-status`, cas `proc=None` géré en une branche |
| ElementTree stdlib pour le parse XML | Réponse Dune plate, pas besoin de lxml/xmltodict | Zéro nouvelle dépendance, conforme à la règle "réutiliser avant de réinventer" |
| `httpx.params=` au lieu de `urllib.parse.quote()` | httpx URL-encode au transport, `media_url` reste lisible dans le code | Moins d'erreurs d'encodage (ex. `%20` vs `+` vs espaces bruts), logs clairs |
| Marqueur `/Films/` ou `/Séries/` pour le mapping | Détection automatique type sans requête DB, variante anglaise `/Series/` acceptée | Fonctionne même pendant un chemin de test/fixture sans accéder au modèle |
| `DuneHDResult` frozen dataclass | Retour structuré immuable au lieu de tuple | Lisibilité (`result.ok`, `result.error`), facile à asserter en test |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minime (lint cleanup pré-existant) |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact :** Aucun écart significatif. Plan exécuté conforme.

### Auto-fixed Issues

**1. [Lint] `import pytest` inutilisé dans `tests/unit/test_player.py`**
- **Found during:** Task 3 verify (ruff check)
- **Issue:** L'import était présent mais non utilisé dans le fichier existant (pré-date ce plan)
- **Fix:** Suppression de la ligne `import pytest` (remplacée par import direct `from fastapi.testclient import TestClient`)
- **Files:** `tests/unit/test_player.py`
- **Verification:** `uv run ruff check` passe sans erreur
- **Justification :** Nécessaire pour satisfaire le `verify` de la Task 3 (`ruff check src/ tests/`) ; la règle "boundaries" n'interdit pas un cleanup trivial de ligne morte

### Deferred Items

Aucun.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `uv run pytest` échoue avec "No such file or directory" sur le binaire `pytest` | `uv sync --all-extras` pour installer les dev dependencies ; commandes de test lancées via `uv run --with pytest --with respx python -m pytest` |

## Next Phase Readiness

**Ready :**
- Backend DuneHD accessible depuis tout le système via `_launch_player()` sans changement d'API côté routes
- Schéma profil prêt pour le Plan 40-02 (UI config) : tous les champs existent déjà dans le JSON, il ne reste qu'à les exposer dans le formulaire
- Tests respx en place comme référence pour les futurs backends HTTP (Chromecast, etc.)

**Concerns :**
- Le test manuel avec un vrai DuneHD n'a pas été effectué dans le cadre de 40-01 (reporté au checkpoint de 40-02 qui couvre end-to-end UI + lecture réelle)
- Le cache de test pytest (`.pytest_cache`) n'a pas été touché, les 90%+ de couverture globale restent à vérifier par un run complet

**Blockers :** None — Plan 40-02 peut démarrer immédiatement.

---
*Phase: 40-lecteur-dunehd, Plan: 01*
*Completed: 2026-04-14*
