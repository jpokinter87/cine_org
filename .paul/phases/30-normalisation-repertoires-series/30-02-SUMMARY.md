---
phase: 30-normalisation-repertoires-series
plan: 02
subsystem: cli
tags: [migrate-series, fix-series-symlinks, mediainfo, guessit, tvdb, symlinks]

requires:
  - phase: 30-01
    provides: code source normalisé (Séries→Series dans le code)
provides:
  - Commande migrate-series (renommage dirs, bulk update DB, rebuild symlinks, reclassification)
  - Commande fix-series-symlinks (pipeline complet mediainfo+guessit+TVDB pour normaliser les symlinks)
affects: [31-nfo-artwork-jellyfin]

tech-stack:
  added: []
  patterns:
    - mediainfo primaire + guessit fallback langue (pipeline identique au workflow)
    - TVDB bulk fetch pour enrichissement titres épisodes
    - rich.Progress pour les processus longs

key-files:
  created:
    - src/adapters/cli/commands/fix_series_symlinks_command.py
    - src/adapters/cli/commands/migrate_series_command.py
    - tests/unit/adapters/cli/test_fix_series_symlinks.py
    - tests/unit/adapters/cli/test_migrate_series.py
  modified:
    - src/adapters/cli/commands/__init__.py
    - src/main.py

key-decisions:
  - "mediainfo primary, guessit fallback : identique au workflow normal"
  - "Normalisation ligatures Œ/Æ et slash/tiret pour comparaison de titres"
  - "SD reconnu comme résolution valide, MPEG-4/XviD/DivX comme codecs valides"
  - "TVDB enrichissement intégré dans fix-series-symlinks (pas besoin d'étape séparée)"

patterns-established:
  - "Réutiliser le pipeline workflow existant plutôt que réinventer (règle CLAUDE.md)"

duration: ~3h
started: 2026-03-01T13:00:00Z
completed: 2026-03-01T16:10:00Z
---

# Phase 30 Plan 02: Migration physique + fix-series-symlinks — Summary

**Commandes migrate-series et fix-series-symlinks : migration structure séries + normalisation complète des symlinks via pipeline mediainfo/guessit/TVDB**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~3h |
| Started | 2026-03-01 13:00 |
| Completed | 2026-03-01 16:10 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files created | 4 |
| Files modified | 2 |
| Tests | 40 (26 fix-series + 14 migrate-series) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Plus de "Séries" fonctionnel | Pass | Références corrigées dans repair_service, maintenance.py, transfer.py, reconcile_command |
| AC-2: migrate-series dry-run | Pass | Rapport détaillé sans modification |
| AC-3: migrate-series exécution | Pass | Renommage dirs + bulk update DB + rebuild symlinks |
| AC-4: Reclassification par genre | Pass | Animation/Mangas/Documentaires déplacés correctement |
| AC-5: Tests passent | Pass | 40 tests passent |

## Accomplishments

- **migrate-series** : commande complète de migration (renommage Séries→Series, Séries TV→TV, update DB, rebuild symlinks, reclassification par genre)
- **fix-series-symlinks** : vérification et reconstruction des symlinks non conformes via le pipeline complet (mediainfo primaire + guessit fallback + TVDB pour titres manquants)
- Correction du tvdb_id de Battlestar Galactica (71173→73545) — illustrant la capacité de diagnostic de la commande
- Normalisation robuste pour comparaison de titres (ligatures Œ/Æ, slash/tiret, SD, MPEG-4)
- Barres de progression rich.Progress pour les deux phases lentes (analyse + correction)

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Tasks 1-3 | `3efa031` | feat | Commandes migrate-series et fix-series-symlinks + tests |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/cli/commands/migrate_series_command.py` | Created | Commande migration structure séries |
| `src/adapters/cli/commands/fix_series_symlinks_command.py` | Created | Commande vérification/réparation symlinks séries |
| `tests/unit/adapters/cli/test_migrate_series.py` | Created | 14 tests migrate-series |
| `tests/unit/adapters/cli/test_fix_series_symlinks.py` | Created | 26 tests fix-series-symlinks |
| `src/adapters/cli/commands/__init__.py` | Modified | Export des nouvelles commandes |
| `src/main.py` | Modified | Enregistrement des commandes CLI |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| mediainfo primaire, guessit fallback langue | Identique au workflow normal — codecs normalisés nativement (x264/x265) | Résultats cohérents avec le reste du pipeline |
| TVDB enrichissement intégré | Évite une étape séparée — enrichit au vol pendant le fix | ~58 titres enrichis pour BSG en une passe |
| SD comme résolution valide | Beaucoup de fichiers anciens en SD — évite faux positifs | -666 faux positifs éliminés |
| Normalisation Œ/Æ et slash/tiret | Titres TVDB avec ligatures vs noms fichiers sans | -71 faux positifs éliminés |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | fix-series-symlinks non prévu dans le plan original |
| Auto-fixed | 3 | Normalisation SD, ligatures, codecs |

**Total impact:** fix-series-symlinks est un ajout majeur mais essentiel — c'est la commande qui rend la normalisation réellement utile en production.

### Scope Additions

**1. Commande fix-series-symlinks**
- **Raison:** La migration des répertoires (plan original) ne suffit pas — les symlinks existants avaient des noms non conformes (specs techniques manquantes, titres absents, mauvais codecs)
- **Impact:** Commande complète de 693 lignes avec pipeline mediainfo+guessit+TVDB
- **Résultat:** ~1000 symlinks corrigés sur la bibliothèque réelle

### Auto-fixed Issues

**1. Reconnaissance SD comme résolution**
- **Issue:** `_check_tech_specs` ne reconnaissait pas "SD" → ~666 faux positifs
- **Fix:** Ajout `" SD" in name_upper` dans la détection

**2. Normalisation ligatures Œ/Æ**
- **Issue:** Titres TVDB "L'Œil de verre" vs symlink "L'Oeil de verre" → faux positifs titre absent
- **Fix:** Décomposition `œ→oe`, `æ→ae` + unification `/→-` dans `_normalize_for_compare`

**3. Codecs MPEG-4/XviD/DivX non reconnus**
- **Issue:** Fichiers anciens avec ces codecs signalés comme "codec manquant"
- **Fix:** Ajout dans `_check_tech_specs`

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Codecs guessit (H.264) vs standard (x264) | Mapping `_GUESSIT_CODEC_MAP` pour convertir |
| BSG mauvais tvdb_id (1978 vs 2004) | Correction manuelle en DB, enrichissement titres |
| 487 épisodes irréductibles (langue manquante) | Limite structurelle — ni mediainfo ni guessit ne détectent la langue |

## Next Phase Readiness

**Ready:**
- Structure séries entièrement normalisée (Series/TV, Series/Animation, etc.)
- Symlinks conformes au format standard
- Compatible Jellyfin

**Concerns:**
- 487 épisodes avec langue indétectable (fichiers anciens sans métadonnée)
- Quelques tvdb_id potentiellement erronés sur d'autres séries (découvert avec BSG)

**Blockers:**
- None

---
*Phase: 30-normalisation-repertoires-series, Plan: 02*
*Completed: 2026-03-01*
