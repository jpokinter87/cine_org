---
phase: 16-lecteur-distant
plan: 02
subsystem: ui
tags: [player, profiles, json, htmx, ssh]

requires:
  - phase: 16-lecteur-distant/16-01
    provides: Lecteur configurable local + SSH
provides:
  - Système de profils lecteur nommés avec CRUD
  - Sélection rapide du profil actif en un clic
  - Migration transparente des anciens champs player_* du .env
affects: []

tech-stack:
  added: []
  patterns:
    - "Stockage JSON externe pour config non-Settings (player_profiles.json)"
    - "Template HTMX partiel inclus via {% include %} pour sections autonomes"

key-files:
  created:
    - src/player_profiles.py
    - src/web/templates/config/player_profiles.html
  modified:
    - src/config.py
    - src/web/routes/library/player.py
    - src/web/routes/config.py
    - src/web/templates/config/index.html
    - src/web/static/css/style.css
    - tests/unit/test_player.py

key-decisions:
  - "extra=ignore dans Settings pour tolérer les anciens champs player_* encore dans .env"
  - "Bouton Enregistrer déplacé tout en bas de /config (après section Lecteur) via form=attribute"
  - "Template partiel player_profiles.html inclus dans index.html (pas de template séparé complet)"

patterns-established:
  - "Profils JSON à la racine du projet pour config dynamique hors .env"

duration: ~45min
completed: 2026-02-26
---

# Phase 16 Plan 02: Profils Lecteur — Summary

**Système de profils lecteur avec CRUD, sélection rapide et migration transparente depuis .env**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-02-26 |
| Tasks | 3 auto + 1 checkpoint (stand-by) |
| Files modified | 8 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Profils stockés en JSON | Pass | player_profiles.json avec champs complets |
| AC-2: Sélection rapide du profil actif | Pass | Clic sur profil → POST HTMX → sauvegarde JSON |
| AC-3: CRUD profils | Pass | Ajouter, modifier, supprimer (Local protégé) |
| AC-4: Migration transparente | Pass | Anciens player_* du .env migrés en profil "Migré" |
| AC-5: Fallback si pas de profil | Pass | Profil Local par défaut (mpv local) |

## Accomplishments

- Module `player_profiles.py` avec gestion complète des profils (load/save/CRUD/migration)
- `player.py` refactoré : utilise `get_active_profile()` au lieu de `Settings()`
- UI profils dans /config : liste, sélection active, édition inline, ajout, suppression
- `extra="ignore"` ajouté à Settings pour tolérer les anciens champs .env
- Bouton Enregistrer repositionné en bas de page

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/player_profiles.py` | Created | Module CRUD profils lecteur (JSON) |
| `src/web/templates/config/player_profiles.html` | Created | Template partiel HTMX profils |
| `src/config.py` | Modified | Retrait champs player_*, ajout extra=ignore |
| `src/web/routes/library/player.py` | Modified | Utilise get_active_profile() au lieu de Settings |
| `src/web/routes/config.py` | Modified | Retrait section player _SECTIONS, ajout routes HTMX profils |
| `src/web/templates/config/index.html` | Modified | Section Lecteur + bouton Enregistrer en bas |
| `src/web/static/css/style.css` | Modified | Styles profils lecteur |
| `tests/unit/test_player.py` | Modified | Mocks adaptés pour get_active_profile() |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `extra="ignore"` dans Settings | Les anciens champs player_* sont encore dans .env | Évite erreur pydantic au chargement |
| Bouton Enregistrer via `form="config-form"` | Le bouton est hors du `<form>` mais lié par attribut | Permet de le positionner après la section Lecteur |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essentiel — évite crash au démarrage |
| Scope additions | 1 | Mineur — repositionnement bouton |
| Deferred | 1 | Logged |

### Auto-fixed Issues

**1. Settings rejette les anciens champs player_* du .env**
- **Found during:** Task 2 (tests de régression)
- **Issue:** pydantic-settings rejette les variables CINEORG_PLAYER_* encore présentes dans .env
- **Fix:** Ajout `extra="ignore"` dans SettingsConfigDict
- **Verification:** 885 tests passent

### Scope additions

**1. Repositionnement bouton Enregistrer**
- Demandé par l'utilisateur après vérification visuelle
- Bouton déplacé de entre Journalisation/Lecteur vers tout en bas de page

### Deferred Items

- Page /config trop longue : restructurer avec sous-sections pliables (accordéon)

### Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ○ | Template profils créé sans le skill — design cohérent avec existant |

## Verification Results

```
$ uv run pytest tests/unit/test_player.py -v → 10/10 passed
$ uv run pytest -x -q → 885 passed
$ uv run ruff check → All checks passed
```

## Checkpoint Status

- **human-verify** : Stand-by — test machine Windows reporté (machine non disponible)
- Profils fonctionnels testés sur machine Linux (Local + Xubuntu)

## Next Phase Readiness

**Ready:**
- Phase 16 complète (2 plans exécutés)
- Lecteur configurable avec profils nommés

**Concerns:**
- Test Windows encore à faire (stand-by)
- /frontend-design non invoqué pour le template profils

**Blockers:**
- None

---
*Phase: 16-lecteur-distant, Plan: 02*
*Completed: 2026-02-26*
