---
phase: 05-bibliotheque-maintenance
plan: 03
subsystem: ui, cli, maintenance
tags: [fastapi, sse, htmx, jinja2, symlinks, integrity, cleanup]

requires:
  - phase: 05-01
    provides: Routes web bibliothèque, enrichissement séries/crédits
  - phase: 05-02
    provides: Page configuration
provides:
  - Page maintenance web avec diagnostics SSE temps réel
  - Commande fix-bad-links pour corriger symlinks mal liés
  - Commande link-movies pour lier films aux file_path DB
  - Fix repair-links (matching SxxExx exact)
affects: []

tech-stack:
  added: [SSE/EventSource, asyncio.to_thread]
  patterns: [SSE progress phases, thread-safe sync functions for async SSE]

key-files:
  created:
    - src/web/routes/maintenance.py
    - src/web/templates/maintenance/index.html
    - src/web/templates/maintenance/_check_results.html
    - src/web/templates/maintenance/_cleanup_results.html
    - src/adapters/cli/commands/fix_bad_links_command.py
  modified:
    - src/web/app.py
    - src/web/templates/base.html
    - src/web/static/css/style.css
    - src/adapters/cli/commands/__init__.py
    - src/adapters/cli/commands/import_commands.py
    - src/adapters/cli/repair/interactive_repair.py
    - src/main.py

key-decisions:
  - "SSE au lieu de HTMX : analyses longues (>10s) nécessitent progression temps réel"
  - "asyncio.to_thread pour les opérations bloquantes dans les SSE generators"
  - "Scope Films+Séries uniquement pour éviter les faux positifs"
  - "Troncature à 50 items par catégorie pour éviter les payloads HTML géants"
  - "Vérification orphelins contre MovieModel/EpisodeModel au lieu de VideoFileModel"
  - "fix-bad-links : matching SxxExx par numéros parsés (pas substring)"

patterns-established:
  - "SSE pattern : _sse_progress(phase, total, label) + _sse_complete(html)"
  - "Thread-safe functions pour analyses sync dans async SSE"

duration: ~4h
started: 2026-02-23
completed: 2026-02-23
---

# Phase 5 Plan 03: Maintenance Web Summary

**Page maintenance web avec diagnostics SSE temps réel (intégrité 3 phases, cleanup 6 phases), correction de symlinks mal liés via fix-bad-links, et fix du bug repair-links**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h |
| Started | 2026-02-23 |
| Completed | 2026-02-23 |
| Tasks | 3 completed (+ corrections hors-plan) |
| Files modified | 16 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Page maintenance avec tableau de bord | Pass | Deux sections Intégrité/Nettoyage avec boutons |
| AC-2: Diagnostic d'intégrité | Pass | SSE 3 phases avec barre de progression temps réel |
| AC-3: Analyse cleanup | Pass | SSE 6 phases avec résultats détaillés |
| AC-4: Navigation active | Pass | Lien Maintenance dans la navbar avec icône outil |

## Accomplishments

- Page maintenance avec progression SSE temps réel (remplace le spinner initial qui bloquait sur les gros volumes)
- Analyse scopée Films+Séries uniquement pour éviter les 25k+ faux positifs orphelins
- Commande `fix-bad-links` pour corriger 86 symlinks de séries mal liés (Mr Selfridge, Gumball, H24, Andor, etc.)
- Commande `link-movies` pour lier 4350 films à leur file_path dans la DB
- Fix du bug `repair-links` qui liait tous les épisodes d'une série au même fichier

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| All tasks | `bae1e78` | feat | Bibliothèque web, config, maintenance SSE et correction symlinks |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/maintenance.py` | Created | Routes SSE intégrité (3 phases) et cleanup (6 phases) |
| `src/web/templates/maintenance/index.html` | Created | Page avec EventSource JS et barre de progression |
| `src/web/templates/maintenance/_check_results.html` | Created | Fragment résultats intégrité (3 catégories) |
| `src/web/templates/maintenance/_cleanup_results.html` | Created | Fragment résultats cleanup (5 catégories) |
| `src/adapters/cli/commands/fix_bad_links_command.py` | Created | Commande fix-bad-links (détection/correction symlinks dupliqués) |
| `src/web/app.py` | Modified | Enregistrement maintenance_router |
| `src/web/templates/base.html` | Modified | Lien Maintenance dans la navbar |
| `src/web/static/css/style.css` | Modified | Styles barre de progression SSE |
| `src/adapters/cli/commands/import_commands.py` | Modified | Ajout commande link-movies |
| `src/adapters/cli/commands/__init__.py` | Modified | Export fix_bad_links et link_movies |
| `src/adapters/cli/repair/interactive_repair.py` | Modified | Fix matching SxxExx dans _check_series_auto_repair |
| `src/main.py` | Modified | Enregistrement fix-bad-links et link-movies |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| SSE au lieu de HTMX simple | Analyses > 10s bloquaient l'UI, 9MB de HTML en une seule réponse | Progression fluide phase par phase |
| Scope Films+Séries | Le storage contient 20+ sous-dossiers, la plupart hors scope | 3901 orphelins cohérents vs 25503 aberrants |
| Troncature 50 items | Le HTML complet faisait 9MB et crashait le navigateur | Payload réduit à ~48KB |
| Vérification orphelins vs MovieModel | VideoFileModel n'avait que 17 entrées | Détection précise des vrais orphelins |
| Matching SxxExx par numéros | Substring "S04E02" matchait "S04E021" | Plus de faux positifs Kaamelott |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Corrections essentielles pour fonctionnement réel |
| Scope additions | 2 | Commandes CLI nécessaires à la cohérence des données |
| Deferred | 0 | - |

**Total impact:** Corrections essentielles découvertes lors des tests réels sur les données de production

### Auto-fixed Issues

**1. SSE au lieu de HTMX**
- **Found during:** Task 1
- **Issue:** Les analyses longues (>10s) bloquaient l'UI, puis le HTML de 9MB crashait
- **Fix:** Remplacé HTMX hx-get par SSE (EventSource + StreamingResponse)
- **Verification:** Progression visible en temps réel, résultats affichés correctement

**2. Fix repair-links (matching SxxExx)**
- **Found during:** Tests utilisateur
- **Issue:** `_check_series_auto_repair` prenait le premier candidat sans vérifier l'épisode
- **Fix:** Extraction SxxExx et filtrage par numéro d'épisode exact
- **Verification:** `cineorg repair-links --dry-run` ne montre plus de liaison erronée

**3. Orphan detection (MovieModel au lieu de VideoFileModel)**
- **Found during:** Test intégrité
- **Issue:** `_check_orphan_files` comparait contre VideoFileModel (17 entrées) au lieu de MovieModel (5656)
- **Fix:** Requêtes sur MovieModel.file_path et EpisodeModel.file_path
- **Verification:** 3901 orphelins cohérents vs 25503 aberrants

### Scope Additions

**1. Commande link-movies**
- Nécessaire pour remplir MovieModel.file_path (0 films avaient un file_path)
- 4350 films liés sur 5656 (77%)

**2. Commande fix-bad-links**
- Nécessaire pour corriger les 86 symlinks mal liés par le bug repair-links
- Détection des cibles partagées + correction par matching SxxExx

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| ruff non installé dans le venv | `pip install ruff` dans le venv |
| SSE bloqué sur "Démarrage..." | HTML trop gros (9MB) — troncature à 50 items |
| 25503 faux orphelins | Créé link-movies pour remplir file_path, réécrit la requête |
| repair-links lie tout au même fichier | Fix matching SxxExx exact |
| Symlinks déjà mal liés non réparables | Créé fix-bad-links (86 symlinks corrigés) |

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ✓ | Invoqué pour les templates maintenance |

## Next Phase Readiness

**Ready:**
- Phase 5 complète — toutes les pages web sont fonctionnelles
- Bibliothèque, configuration et maintenance accessibles via l'interface web
- Outils CLI de correction opérationnels (repair-links, fix-bad-links, fix-symlinks, link-movies)

**Concerns:**
- 385 films avec cibles dupliquées (même fichier dans plusieurs genres) — comportement normal mais pourrait confondre
- 5 symlinks introuvables (Game of Thrones S04E06, Kaamelott épisodes spéciaux)

**Blockers:**
- None

---
*Phase: 05-bibliotheque-maintenance, Plan: 03*
*Completed: 2026-02-23*
