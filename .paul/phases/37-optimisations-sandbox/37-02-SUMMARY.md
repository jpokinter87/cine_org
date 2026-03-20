---
phase: 37-optimisations-sandbox
plan: 02
subsystem: maintenance, storage
tags: [sandbox, orphans, integrity, symlinks, fastapi, htmx, sse]

requires:
  - phase: 37-01
    provides: corbeille maintenance, page maintenance avec SSE
provides:
  - SandboxService complet (déplacement, liste, suppression, réinjection)
  - Interface web sandbox dans page maintenance
  - Nettoyage automatique symlinks résiduels (séquelles)
  - Garde-fou _is_subdivision_path contre sandbox massif
affects: [maintenance, transfer, integrity]

tech-stack:
  added: []
  patterns: [SSE batch progression, stale symlink detection par titre+année+SxxExx]

key-files:
  created:
    - src/services/sandbox_service.py
    - src/web/templates/maintenance/_sandbox_section.html
    - tests/unit/test_sandbox_service.py
  modified:
    - src/config.py
    - src/container.py
    - src/web/routes/maintenance.py
    - src/web/routes/transfer.py
    - src/web/templates/maintenance/_check_results.html
    - src/web/templates/maintenance/index.html

key-decisions:
  - "sandbox_dir = storage_dir/.sandbox (même volume, pas de copie réseau)"
  - "Réinjection dans downloads/Films ou downloads/Series (pas à la racine)"
  - "Nettoyage séquelles par clé titre+année pour films, titre+SxxExx pour épisodes"
  - "Garde-fou _is_subdivision_path : double protection resolve + sandbox"

patterns-established:
  - "SSE par batch de N fichiers pour progression réelle"
  - "htmx.process() obligatoire après innerHTML sur résultats SSE"
  - "Dialogue overlay custom au lieu de confirm() natif"

duration: ~4h (avec investigation bug subdivision)
started: 2026-03-20T10:00:00+01:00
completed: 2026-03-20T16:00:00+01:00
---

# Phase 37 Plan 02: Sandbox orphelins — Summary

**SandboxService avec interface web maintenance : isolation, suppression et réinjection des fichiers orphelins, plus fix critique du sandbox transfer qui détruisait des subdivisions entières.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h |
| Started | 2026-03-20 10:00 |
| Completed | 2026-03-20 16:00 |
| Tasks | 3 completed |
| Files modified | 9 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Configuration sandbox | Pass | `sandbox_dir` optionnel, défaut `storage_dir/.sandbox` |
| AC-2: Déplacement orphelins vers sandbox | Pass | SSE avec progression par batch, dialogue overlay |
| AC-3: Interface web sandbox | Pass | Carte dans /maintenance, tableau avec checkbox, actions |
| AC-4: Suppression définitive depuis sandbox | Pass | Dialogue confirmation, nettoyage dossiers vides |
| AC-5: Réinjection dans le workflow | Pass | Fichiers placés dans downloads/Films ou downloads/Series |

## Accomplishments

- SandboxService complet avec 14 tests unitaires (sandbox, list, delete, reinject)
- Interface web sandbox intégrée dans /maintenance avec progression SSE
- Nettoyage automatique des symlinks résiduels lors du diagnostic d'intégrité (matching titre+année+SxxExx+format scene)
- Fix critique : garde-fou `_is_subdivision_path()` empêchant le sandbox transfer de détruire des subdivisions entières

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1+2+3 | `be10ea6` | feat | SandboxService + interface web + fix subdivision |
| Fix réinjection | `37fa1e6` | fix | Réinjection dans downloads/Films ou Series |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/sandbox_service.py` | Created | Service sandbox : déplacement, liste, suppression, réinjection |
| `src/web/templates/maintenance/_sandbox_section.html` | Created | Partial Jinja2 pour la section sandbox |
| `tests/unit/test_sandbox_service.py` | Created | 14 tests unitaires |
| `src/config.py` | Modified | Ajout sandbox_dir + resolved_sandbox_dir |
| `src/container.py` | Modified | Enregistrement SandboxService |
| `src/web/routes/maintenance.py` | Modified | Routes sandbox SSE + nettoyage séquelles |
| `src/web/routes/transfer.py` | Modified | Garde-fou _is_subdivision_path |
| `src/web/templates/maintenance/_check_results.html` | Modified | Bouton "Sandboxer les orphelins" |
| `src/web/templates/maintenance/index.html` | Modified | Carte sandbox + dialogues + CSS + JS |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| sandbox_dir = storage_dir/.sandbox | Même volume physique, pas de copie réseau | Performances optimales |
| Réinjection dans downloads/{Films,Series} | Le scan workflow distingue par sous-répertoire | Détection type correcte |
| Matching séquelles par titre+année+SxxExx | Couvre formats CineOrg, scene, et épisodes sans année | ~500 séquelles nettoyées automatiquement |
| Double garde-fou subdivision | _resolve_storage_path + _sandbox_existing | Empêche le bug critique de se reproduire |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 4 | Corrections essentielles découvertes en test |
| Scope additions | 2 | Nettoyage séquelles + fix subdivision (critiques) |
| Deferred | 0 | - |

**Total impact:** Scope élargi par nécessité — le bug subdivision était critique et pré-existant.

### Auto-fixed Issues

**1. htmx.process() manquant sur résultats SSE**
- **Found during:** Task 2
- **Issue:** Les boutons hx-post injectés via innerHTML SSE n'étaient pas activés par HTMX
- **Fix:** Ajout `htmx.process(results)` après chaque injection innerHTML
- **Verification:** Boutons fonctionnels après injection

**2. confirm() natif → dialogue overlay custom**
- **Found during:** Checkpoint
- **Issue:** Le confirm() du navigateur ne respectait pas la charte graphique
- **Fix:** Dialogue overlay violet avec icône sandbox
- **Verification:** Cohérence visuelle avec les autres dialogues

**3. PermissionError sandbox_dir**
- **Found during:** Checkpoint
- **Issue:** Défaut `storage_dir.parent/.sandbox` = `/media/.sandbox` (pas accessible)
- **Fix:** Changé en `storage_dir/.sandbox` = `/media/NAS64/.sandbox`
- **Verification:** Création automatique du répertoire

**4. SSE progression avec concurrent.futures**
- **Found during:** Checkpoint
- **Issue:** Pattern queue+executor trop complexe, pas de données envoyées
- **Fix:** Simplifié en batch de 10 fichiers avec asyncio.to_thread
- **Verification:** Barre de progression fonctionnelle

### Scope Additions

**1. Nettoyage automatique des symlinks résiduels**
- Découvert pendant les tests : des centaines de symlinks cassés étaient des séquelles de reclassement
- Matching par titre+année (films), titre+SxxExx (épisodes), format scene (fichiers bruts)
- ~500 séquelles nettoyées automatiquement au diagnostic

**2. Fix critique _sandbox_existing (bug pré-existant)**
- Découvert en production : `_resolve_storage_path` résolvait vers un répertoire de subdivision (`E-F/`) au lieu de la série
- `storage_path.rglob("*")` matchait alors S01E01 dans toutes les séries de la subdivision → 561 fichiers sandboxés à tort
- Fix : `_is_subdivision_path()` + double garde-fou dans resolve et sandbox

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 561 fichiers sandboxés à tort par transfer.py | Restauration manuelle depuis .sandbox/Series/ → NAS64/Series/ |
| Doublons légitimes réinjectés (ex: Le Plaisir en Comédie dramatique) | Nettoyés manuellement, workflow les détecte correctement |

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ✓ | Chargé avant APPLY |

## Next Phase Readiness

**Ready:**
- Sandbox fonctionnel avec interface complète
- Garde-fous en place pour protéger la vidéothèque
- Phase 37 complète (2/2 plans)

**Concerns:**
- Le bug subdivision pré-existait depuis la phase 35 — vérifier s'il a causé des dégâts non détectés dans les sessions précédentes

**Blockers:**
- None

---
*Phase: 37-optimisations-sandbox, Plan: 02*
*Completed: 2026-03-20*
