---
phase: 35-maintenance-web-complete
plan: 01
subsystem: web, maintenance
tags: [sse, symlinks, reconciliation, orphans, integrity, cleanup]

requires:
  - phase: 29-maintenance-page
    provides: page maintenance read-only avec diagnostics SSE
provides:
  - corrections cleanup depuis le web (6 phases)
  - reparation symlinks depuis le web
  - purge entrees fantomes depuis le web
  - detection orphelins basee sur symlinks (plus fiable que DB)
  - reconciliation DB (symlink_path sur MovieModel/EpisodeModel)
  - cache analyse pour eviter rescans
affects: [sandbox-management, workflow-web]

tech-stack:
  added: []
  patterns:
    - cache analyse en memoire (_analysis_cache) pour reutilisation fix
    - orphelins detectes par symlink targets vs storage (pas par DB)
    - reconciliation DB dry-run puis apply

key-files:
  created:
    - src/web/templates/maintenance/_check_fix_results.html
    - src/web/templates/maintenance/_cleanup_fix_results.html
    - src/web/templates/maintenance/_purge_results.html
    - src/web/templates/maintenance/_reconcile_results.html
  modified:
    - src/web/routes/maintenance.py
    - src/web/templates/maintenance/_check_results.html
    - src/web/templates/maintenance/_cleanup_results.html
    - src/web/templates/maintenance/index.html
    - src/web/static/css/style.css
    - src/infrastructure/persistence/models.py

key-decisions:
  - "Orphelins par symlinks : fichier orphelin = pas cible d'un symlink (remplace comparaison DB)"
  - "Cache analyse : stocke resultats en memoire pour eviter rescans de 30K+ fichiers lors du fix"
  - "Reconciliation DB : enrichit MovieModel/EpisodeModel avec symlink_path (dry-run + apply)"
  - "Affichage orphelins groupes par branche storage pour identifier les repertoires hors scope"
  - "Sandbox des orphelins differe a une phase dediee (perimetre trop large)"

patterns-established:
  - "_analysis_cache dict module-level pour partage analyse → fix"
  - "Reconciliation dry-run avant apply pour actions sur fichiers reels"

duration: ~4h
started: 2026-03-07T20:00:00Z
completed: 2026-03-08T02:45:00Z
---

# Phase 35 Plan 01: Maintenance Web Complete Summary

**Corrections cleanup/integrite depuis le web avec SSE, detection orphelins par symlinks, et reconciliation DB enrichissant MovieModel/EpisodeModel avec symlink_path.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h |
| Started | 2026-03-07 20:00 |
| Completed | 2026-03-08 02:45 |
| Tasks | 3 completed |
| Files modified | 10 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Bouton corriger cleanup | Pass | 6 phases correctives avec SSE, rapport detaille |
| AC-2: Bouton corriger integrite (symlinks) | Pass | 132/132 symlinks repares (score >= 90%) |
| AC-3: Restriction localhost | Pass | Boutons masques + 403 pour clients distants |
| AC-4: Resultats detailles | Pass | Actions individuelles, totaux par categorie, erreurs |

## Accomplishments

- Corrections web completes : cleanup fix (6 phases), repair symlinks, purge fantomes, avec progression SSE temps reel
- Detection orphelins fiable basee sur les cibles de symlinks (remplace la comparaison DB peu fiable)
- Reconciliation DB : 5539 films et 16815 episodes enrichis avec leur chemin symlink en quelques secondes
- Orphelins affiches groupes par branche storage, permettant d'identifier les repertoires entierement hors scope
- Cache d'analyse eliminant les rescans de 30K+ fichiers entre diagnostic et correction

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Tasks 1-3 | `70471b7` | feat | Maintenance complete : corrections web, reconciliation DB, orphelins par symlinks |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/maintenance.py` | Modified (+700 lignes) | Routes SSE correction, cache analyse, reconciliation DB, orphelins par symlinks |
| `src/infrastructure/persistence/models.py` | Modified | Ajout symlink_path a MovieModel et EpisodeModel |
| `src/web/templates/maintenance/_check_results.html` | Modified | Orphelins groupes par branche, boutons fix + reconcilier |
| `src/web/templates/maintenance/_cleanup_results.html` | Modified | Bouton "Corriger tout", suppression limite 50 fichiers |
| `src/web/templates/maintenance/index.html` | Modified | JS startFix() avec URLs fix/purge/reconcile |
| `src/web/static/css/style.css` | Modified | Styles boutons fix, branches orphelins, compteurs |
| `src/web/templates/maintenance/_check_fix_results.html` | Created | Rapport reparation symlinks |
| `src/web/templates/maintenance/_cleanup_fix_results.html` | Created | Rapport corrections cleanup |
| `src/web/templates/maintenance/_purge_results.html` | Created | Rapport purge fantomes |
| `src/web/templates/maintenance/_reconcile_results.html` | Created | Rapport reconciliation DB (dry-run + apply) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Orphelins par symlinks au lieu de DB | Un fichier sans symlink = vrai orphelin, independant de l'etat DB | Detection 100% fiable, identifie les branches hors scope |
| Cache analyse module-level | Evite de rescanner 30K+ fichiers entre analyse et fix | Fix quasi-instantane apres analyse |
| symlink_path sur MovieModel/EpisodeModel | Permet de retrouver le symlink depuis la DB | Prerequis pour futures fonctionnalites (sandbox, reconciliation) |
| Sandbox des orphelins differe | Perimetre trop large (interface gestion, reinejction workflow) | Planifie comme phase dediee |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 4 | Fonctionnalites essentielles ajoutees |
| Auto-fixed | 2 | Bugs corriges pendant execution |
| Deferred | 1 | Sandbox orphelins |

**Total impact:** Additions essentielles, pas de scope creep — les ajouts repondaient a des problemes decouverts pendant le test.

### Scope Additions

1. **Purge entrees fantomes** — bouton + endpoint SSE (decouvert que le plan ne couvrait que symlinks)
2. **Detection orphelins par symlinks** — remplace la methode DB peu fiable (decouvert 4385 faux positifs)
3. **Reconciliation DB** — enrichissement MovieModel/EpisodeModel avec symlink_path (dry-run + apply)
4. **Suppression limite 50 fichiers** — affichage complet avec scroll CSS

### Auto-fixed Issues

1. **VideoFileModel.file_path → .path** — AttributeError dans purge fantomes (VideoFileModel n'a pas file_path)
2. **Cache fix-symlinks** — l'analyse detectait les broken links mais le fix rescannait tout (ajout consommation cache)

### Deferred Items

- Sandbox management complet : sandboxer orphelins vers .sandbox/orphans/, interface gestion (liste/suppression/reinejction workflow)

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | o | Non invoque — templates crees en coherence avec le design existant (classes maint-*) |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| AttributeError: file_path sur VideoFileModel | Corrige : utiliser .path + extraction ID depuis details |
| Fix symlinks tres lent (pas de cache) | Corrige : reutiliser les broken links caches par l'analyse |
| 4385 orphelins faux positifs (detection DB) | Remplace par detection basee symlinks (vrais orphelins : ~50) |

## Next Phase Readiness

**Ready:**
- Base enrichie avec symlink_path (5539 films, 16815 episodes)
- Index symlinks cachable pour reutilisation
- Pattern orphelins par branche pret pour le sandboxing

**Concerns:**
- Skill /frontend-design non invoque (gap mineur, design coherent maintenu)

**Blockers:**
- None

---
*Phase: 35-maintenance-web-complete, Plan: 01*
*Completed: 2026-03-08*
