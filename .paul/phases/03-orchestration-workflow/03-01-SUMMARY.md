---
phase: 03-orchestration-workflow
plan: 01
subsystem: web
tags: [fastapi, sse, htmx, workflow, async]

requires:
  - phase: 02-validation-visuelle
    provides: Routes validation, pattern HTMX, enrichissement API
provides:
  - Page workflow web avec lancement scan → matching → auto-validation
  - Suivi de progression temps réel via SSE
  - Cascade auto-validation épisodes séries (web)
  - Recherche IMDB par ID externe (find_by_imdb_id)
affects: [04-transfert-conflits]

tech-stack:
  added: [EventSource SSE, asyncio.create_task]
  patterns: [WorkflowProgress shared state, SSE event stream]

key-files:
  created:
    - src/web/routes/workflow.py
    - src/web/templates/workflow/index.html
    - src/web/templates/workflow/_progress.html
    - src/web/templates/workflow/_results.html
  modified:
    - src/web/routes/validation.py
    - src/web/static/css/style.css
    - src/web/app.py
    - src/adapters/api/tmdb_client.py
    - src/adapters/api/tvdb_client.py
    - src/services/validation.py
    - src/services/workflow/matching_step.py

key-decisions:
  - "Pas de réutilisation de WorkflowService.execute() — services individuels réutilisés directement"
  - "Cascade auto-validation séries ajoutée dans la route web validate_candidate"
  - "Réinitialisation complète de la DB à chaque lancement workflow (pas de nettoyage sélectif)"
  - "Suppression du filtre exact_match par episode count (favorisait les documentaires)"

patterns-established:
  - "SSE via StreamingResponse + EventSource pour progression temps réel"
  - "WorkflowProgress class comme état partagé entre asyncio.Task et SSE"
  - "Tooltips sur résultats workflow (listes de fichiers par catégorie)"

duration: ~6h (sessions multiples avec UAT itérative)
started: 2026-02-23T13:30:00Z
completed: 2026-02-23T16:00:00Z
---

# Phase 3 Plan 01: Orchestration Workflow Summary

**Workflow web complet (scan → matching → auto-validation) avec SSE temps réel, cascade auto-validation séries, et corrections matching TVDB**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~6h (UAT itérative) |
| Started | 2026-02-23 13:30 |
| Completed | 2026-02-23 16:00 |
| Tasks | 2 completed (1 auto + 1 checkpoint) |
| Files created | 4 |
| Files modified | 8 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Page workflow avec lancement | Pass | GET /workflow + POST /start + filtre type |
| AC-2: Suivi de progression SSE | Pass | 4 étapes (réinit, scan, matching, auto-validation) avec barre animée |
| AC-3: Affichage des résultats | Pass | Compteurs + tooltips fichiers + lien /validation si pending > 0 |
| AC-4: Gestion fichiers sous-dimensionnés | Pass | Ignorés automatiquement, compteur affiché dans résultats |
| AC-5: Gestion des erreurs | Pass | Event SSE error + affichage message + arrêt propre |

## Accomplishments

- Workflow web fonctionnel de bout en bout (scan → matching → auto-validation → résultats)
- Suivi progression temps réel via SSE avec 4 étapes visuelles et barre animée
- Cascade auto-validation épisodes séries dans la route web (valider 1 épisode → auto-valide tous les épisodes de la même série)
- Correction du filtre `_filter_by_episode_count` qui favorisait les documentaires au lieu des séries
- Recherche IMDB par ID externe via `tmdb_client.find_by_imdb_id()`
- Correction des URLs posters TVDB (préfixe `/banners/` manquant)
- Tooltips sur les résultats workflow (listes de fichiers par catégorie au hover)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/workflow.py` | Created | Routes workflow (GET /, POST /start, GET /progress SSE) + run_web_workflow |
| `src/web/templates/workflow/index.html` | Created | Page principale workflow (formulaire + état actuel + pipeline) |
| `src/web/templates/workflow/_progress.html` | Created | Fragment progression SSE (barre, étapes, compteurs, JS EventSource) |
| `src/web/templates/workflow/_results.html` | Created | Fragment résultats (compteurs, tooltips, lien validation) |
| `src/web/app.py` | Modified | Montage workflow_router |
| `src/web/static/css/style.css` | Modified | Styles workflow, progression, résultats, tooltips, year input, select |
| `src/web/routes/validation.py` | Modified | Cascade auto-validation séries + recherche IMDB + normalisation année |
| `src/adapters/api/tmdb_client.py` | Modified | Ajout find_by_imdb_id() via endpoint /find/{external_id} |
| `src/adapters/api/tvdb_client.py` | Modified | Fix URLs posters (slash + /banners/ prefix) |
| `src/services/validation.py` | Modified | Recherche IMDB via find_by_imdb_id |
| `src/services/workflow/matching_step.py` | Modified | Suppression filtre exact_match, simplification _filter_by_episode_count |
| `tests/unit/services/test_workflow.py` | Modified | Mise à jour tests après suppression exact_match |
| `tests/unit/services/test_validation.py` | Modified | Fix AsyncMock pour find_by_imdb_id |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Services individuels au lieu de WorkflowService | WorkflowService est couplé à Rich/Confirm (CLI) | Code dupliqué mais découplé |
| Suppression filtre exact_match episode count | Favorisait systématiquement les mini-documentaires | Matching séries corrigé |
| Réinitialisation DB complète à chaque workflow | Évite les orphelins et données stale | Message clarifié "enregistrements précédents supprimés" |
| Cascade dans route web (pas dans service) | La logique CLI est dans le mixin, le web a son propre flux | Cascade implémentée dans validation.py |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 5 | Bugs critiques corrigés pendant UAT |
| Scope additions | 2 | Fonctionnalités nécessaires découvertes |
| Deferred | 0 | - |

**Total impact:** Corrections essentielles pour un matching séries fonctionnel, pas de scope creep.

### Auto-fixed Issues

**1. [Matching] Filtre exact_match favorisait les documentaires**
- **Found during:** UAT checkpoint
- **Issue:** Le filtre comparait max_episode_in_batch au nombre d'épisodes de la saison TVDB, éliminant les vraies séries (24 épisodes) au profit de mini-docs (1-3 épisodes)
- **Fix:** Suppression complète du filtre exact_match dans matching_step.py et workflow.py
- **Verification:** Séries Lost, Heroes, Colony trouvées correctement après fix

**2. [TVDB] URLs posters retournant 403**
- **Found during:** UAT checkpoint
- **Issue:** URLs manquaient le préfixe `/banners/` et parfois le `/` initial
- **Fix:** Double vérification dans tvdb_client.py: startswith("/") puis startswith("/banners/")
- **Verification:** curl retourne 200 après fix

**3. [Validation] Recherche IMDB par ID échouait**
- **Found during:** UAT checkpoint
- **Issue:** Pas de méthode find_by_imdb_id dans tmdb_client
- **Fix:** Ajout find_by_imdb_id() utilisant l'endpoint TMDB /find/{external_id}
- **Verification:** Recherche tt1234567 fonctionne

**4. [Web] Compteurs "État actuel" stale après workflow**
- **Found during:** UAT checkpoint
- **Issue:** Section "État actuel" gardait les chiffres du chargement initial
- **Fix:** Mise à jour JS des compteurs quand SSE envoie l'event "complete"

**5. [Web] Message "orphelins nettoyés" ambigu**
- **Found during:** UAT checkpoint
- **Issue:** "Orphelins" évoquait des symlinks brisés
- **Fix:** Renommé en "enregistrements précédents supprimés"

### Scope Additions

**1. Cascade auto-validation séries (web)**
- Pas dans le plan original mais essentiel : valider un épisode auto-valide les autres
- Implémenté dans `_auto_validate_series_episodes()` de validation.py

**2. Tooltips résultats workflow**
- Listes de fichiers par catégorie au hover sur les compteurs
- Amélioration UX découverte pendant les tests

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Séries retournent documentaires au lieu de vrais résultats | Suppression filtre exact_match (3 itérations) |
| TVDB poster 403 | Ajout préfixe /banners/ pour toutes les URLs |
| find_by_imdb_id non-async dans tests | Changement MagicMock → AsyncMock |
| Cache TVDB corrompu après fix poster | Purge manuelle des entrées tvdb:details:* |
| Recherche sans année cassait le formulaire | Conversion type année Optional[str] → int |

## Next Phase Readiness

**Ready:**
- Workflow web complet (scan → matching → auto-validation)
- Validation manuelle web avec cascade séries
- Fondation SSE réutilisable pour Phase 4 (progression transfert)

**Concerns:**
- Code dupliqué entre workflow web (routes/workflow.py) et CLI (matching_step.py) pour le matching et le filtrage — un refactoring futur pourrait extraire la logique commune

**Blockers:**
- None

---
*Phase: 03-orchestration-workflow, Plan: 01*
*Completed: 2026-02-23*
