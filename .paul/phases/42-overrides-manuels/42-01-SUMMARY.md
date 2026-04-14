---
phase: 42-overrides-manuels
plan: 01
subsystem: workflow
tags: [tvdb, overrides, season-episode-count, anomaly-detection, sqlmodel, htmx]

requires:
  - phase: 03-orchestration-workflow
    provides: WorkflowService, scan → match → auto-validation pipeline
  - phase: 06-validation
    provides: ValidationService.validate_candidate, pending_validations table

provides:
  - SeasonOverrideModel (table season_overrides) : stockage persistant des découpages alternatifs
  - Colonne EpisodeModel.is_extra : flag des épisodes hors canon TVDB
  - filter_by_episode_count + _filter_by_episode_count_compatibility : consultation de l'override au matching et à l'auto-validation
  - AnomalyDetector : détection post-workflow des groupes (série, saison) où episode > canon
  - 3 routes HTMX : /workflow/anomalies/{accept,dismiss,trash}
  - Section « Cas particuliers à traiter » dans le résumé workflow (rendu JS côté SSE complete)
  - Bouton accept : override + validation groupée de tous les pendings du groupe

affects:
  - phase 41 Jellyfin (is_extra peut piloter l'affichage "specials")
  - phase 42-02 métadonnées manuelles (prochaine extension, pattern override similaire)

tech-stack:
  added: []
  patterns:
    - "Override DB consulté par les filtres avec fallback retro-compatible (session=None)"
    - "AnomalyDetector en fin de workflow, résultat sérialisé dans le payload SSE complete"
    - "Fabrication de SearchResult fallback quand le candidat TVDB a été filtré du pipeline"

key-files:
  created:
    - src/services/anomaly_detector.py
    - tests/unit/test_pending_factory.py
    - tests/unit/test_anomaly_detector.py
    - tests/unit/test_workflow_routes.py
    - scripts/reset_the_big_c.py
    - scripts/reset_big_c_validations.py
  modified:
    - src/infrastructure/persistence/models.py (SeasonOverrideModel + EpisodeModel.is_extra)
    - src/infrastructure/persistence/database.py (migration 10)
    - src/infrastructure/persistence/repositories/episode_repository.py (mapping is_extra)
    - src/core/entities/media.py (Episode.is_extra)
    - src/services/workflow/pending_factory.py (session + _lookup_override_count)
    - src/services/workflow/matching_step.py (propage session)
    - src/adapters/cli/auto_validator.py (session + consultation override)
    - src/adapters/cli/batch_builder.py (canonical_count + is_extra sur création Episode)
    - src/adapters/cli/commands/validate_commands.py (propage session)
    - src/web/routes/workflow.py (anomaly_groups + 3 routes + fallback SearchResult)
    - src/web/templates/workflow/_results.html (section Jinja fallback)
    - src/web/templates/workflow/_progress.html (rendu JS des anomalies à la complétion SSE)
    - src/web/static/css/style.css (classes .workflow-anomalies, .anomaly-*)

key-decisions:
  - "Override persisté en table dédiée season_overrides (pas JSON inline dans series)"
  - "Flag is_extra posé au niveau Episode, pas au niveau VideoFile (plus proche du métier)"
  - "max(tvdb_count, override.episode_count) pour rester cohérent quand l'utilisateur sous-estime"
  - "AnomalyDetector refait sa propre recherche TVDB sur title/year guessit (découpage des responsabilités)"
  - "Seuil similarité titre 0.7 dans AnomalyDetector pour éviter faux positifs (The Big Bake etc.)"
  - "Route accept fabrique un SearchResult fallback quand le candidat cible a été filtré du pipeline"
  - "Rendu anomalies en JS côté _progress.html (parité avec les autres compteurs SSE)"

patterns-established:
  - "Session optionnelle dans les filtres de matching (rétro-compat avec tests sans DB)"
  - "Payload SSE complete inclut les structures métier nécessaires au rendu JS"
  - "Script scripts/reset_*.py avec dry-run par défaut et --apply explicite pour opérations destructives"

duration: ~5h (2 sessions)
started: 2026-04-14T09:00:00Z
completed: 2026-04-14T19:45:00Z
---

# Phase 42 Plan 01 : Overrides d'épisodes hors canon TVDB — Summary

**Détection automatique + résolution groupée des séries dont le découpage local dépasse le canon TVDB, via override persistant (table `season_overrides`), flag `is_extra` sur les épisodes, et section « Cas particuliers à traiter » dans le résumé workflow avec action 1-clic.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5h réparties sur 2 sessions |
| Started | 2026-04-14 matin |
| Completed | 2026-04-14 19:45 |
| Tasks | 3 tâches principales (7 sous-tâches) |
| Files modified | 12 (+ 6 fichiers créés) |
| Tests ajoutés | 17 (4 season_override existants + 4 pending_factory + 5 anomaly_detector + 4 workflow_routes) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Modèle d'override persistant | ✓ | `test_season_override.py` 5/5 verts |
| AC-2: Les 2 filtres respectent l'override | ✓ | `test_pending_factory.py` 4/4 verts, propagation `session` dans matching_step et workflow web |
| AC-3: Détection des groupes d'anomalies | ✓ | `test_anomaly_detector.py` 5/5 verts (algo refait = search TVDB fresh) |
| AC-4: Section anomalies dans résumé workflow | ✓ | Validé visuellement (The Big C — Saison 4, 4 canon / 4 hors canon, chips E05-E08) |
| AC-5: Acceptation groupée crée override + valide | ✓ | Validé E2E : 1 override (161501, 4, 8), 4 pendings VALIDATED, 4 EpisodeModel avec is_extra=1 |
| AC-6: Dismiss laisse les pendings en l'état | ✓ | `test_dismiss_noop` vert |
| AC-7: Corbeille supprime le groupe | ✓ | `test_trash_removes_pendings` vert (reject_pending × N) |
| AC-8: Cycle résolu sans re-blocage | ✓ | Validé empiriquement : 2e run → 4 auto-validés via override |
| AC-9: Pas de régression | ✓ | 1140/1140 tests verts (hors tests/manual/) |

## Accomplishments

- **Cas *The Big C* S04E05-E08 débloqué end-to-end** : détection automatique au résumé workflow, acceptation en 1 clic, override persisté, 4 épisodes validés + transférés avec `is_extra=True` et titres TVDB vides (attendu hors canon).
- **Pipeline de matching rétro-compatible** : les filtres consultent l'override quand une session DB est disponible, sinon comportement strictement identique à l'existant (tests existants intouchés).
- **Détecteur indépendant du pipeline** : AnomalyDetector refait sa propre recherche TVDB à partir du filename parsé, avec seuil de similarité titre, ce qui évite les faux positifs liés au filtrage amont.

## Task Commits

Le plan a été livré en une seule session d'exécution (pas de découpage atomique par tâche). Commits précédents dans l'historique :

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1 : socle DB | `63ee104` | feat | SeasonOverrideModel + EpisodeModel.is_extra + migration 10 + 5 tests |
| Tasks 2+3 (non commités) | — | feat | Filtres override + AnomalyDetector + UI anomalies + fallback route accept |

**À commiter** : tous les changements des Tasks 2 et 3 sont encore en working tree, à regrouper en un commit `feat(phase-42-01): anomaly detection + override acceptance flow`.

## Files Created/Modified

Voir frontmatter `key-files`. Résumé :

| File | Change | Purpose |
|------|--------|---------|
| `src/services/anomaly_detector.py` | Created | Service de détection des groupes (série, saison) hors canon |
| `src/web/routes/workflow.py` | Modified | 3 routes anomalies + AnomalyDetector en fin de workflow + payload SSE étendu + fallback SearchResult |
| `src/web/templates/workflow/_progress.html` | Modified | Rendu JS des anomalies côté client à la réception de l'event SSE complete |
| `src/web/static/css/style.css` | Modified | ~180 lignes CSS pour `.workflow-anomalies` + `.anomaly-*` (thème amber) |
| `src/adapters/cli/batch_builder.py` | Modified | Récupération `canonical_count` + positionnement `is_extra` à la création d'Episode |
| `src/services/workflow/pending_factory.py` | Modified | Param `session` + helper `_lookup_override_count` |
| `src/adapters/cli/auto_validator.py` | Modified | Param `session` dans `_filter_by_episode_count_compatibility` et `auto_validate_files` |
| `scripts/reset_the_big_c.py` | Created | One-shot : remet la série en état « tout juste téléchargée » (storage → downloads + clean DB) |
| `scripts/reset_big_c_validations.py` | Created | One-shot : purge pendings validés + override pour retester la route accept |
| Tests | Created/Modified | 17 tests phase 42-01, 100% verts |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| AnomalyDetector refait sa propre recherche TVDB | Le filtre `filter_by_episode_count` élimine The Big C du set de candidats au moment du matching, donc `pending.candidates` ne contient jamais la série cible | Détecteur indépendant et robuste, au prix d'un search TVDB supplémentaire par groupe (avec cache interne) |
| Seuil de similarité titre 0.7 | Éviter que "The Big Bake" ne soit retenu comme match pour "The Big C" | Faux positifs filtrés |
| Route accept fabrique un SearchResult fallback | Même raison que ci-dessus : la série cible est absente de `pending.candidates`, donc le matching par ID échoue | Validation groupée fonctionne au 1er clic (bug corrigé après retour utilisateur) |
| Rendu anomalies en JS pur | Le template Jinja `_results.html` n'est pas rendu lors du live SSE, seul le rendu JS de `_progress.html` construit le DOM à la complétion | Parité avec les autres compteurs + attributs HTMX activés via `htmx.process()` |
| Scripts de reset avec dry-run par défaut | Opérations destructives sur storage/DB/symlinks → filet de sécurité | 0 perte de données, validation utilisateur avant apply |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Corrections essentielles après retour utilisateur, pas de scope creep |
| Scope additions | 0 | — |
| Deferred | 1 | UX polish mineur (liste /validation) |

### Auto-fixed Issues

**1. [AnomalyDetector] The Big C absent de `pending.candidates` empêchait la détection**
- **Found during:** Test UI end-to-end, bloc anomalies invisible
- **Issue:** L'algorithme original lisait le top candidat TVDB depuis `pending.candidates`, or `filter_by_episode_count` avait déjà éliminé la série cible quand `episode > canon`
- **Fix:** Refactor : groupage par `(title guessit, year, season)` + `tvdb_client.search()` fresh + similarité de titre ≥ 0.7
- **Files:** `src/services/anomaly_detector.py`, `tests/unit/test_anomaly_detector.py`
- **Verification:** 5/5 tests verts, bloc anomalies visible dans l'UI

**2. [Route accept] validate_candidate silencieux faute de candidat matching**
- **Found during:** Test UI, clic « Accepter » créait l'override mais laissait les 4 pendings en PENDING
- **Issue:** La route cherchait `c.source == "tvdb" and str(c.id) == str(tvdb_id)` dans `pending.candidates` → toujours None → skip
- **Fix:** Fallback : fabrication d'un `SearchResult(id=tvdb_id, title=group.series_title, year=group.series_year, source="tvdb")` quand aucun match dans la liste
- **Files:** `src/web/routes/workflow.py`, `tests/unit/test_workflow_routes.py`
- **Verification:** `test_accept_creates_override_and_validates` modifié pour simuler pendings sans la série cible, vérifie que `validate_candidate` reçoit un SearchResult avec id correct

### Deferred Items

- **UX polish `/validation`** : les 4 épisodes validés via la route accept n'apparaissent pas dans la section « Auto-validés » (car `auto_validated=False`). Ajouter une section « Validés via action groupée » ou un badge distinct. Impact faible : la validation DB est correcte, c'est uniquement l'affichage.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Migration `is_extra` non appliquée sur DB réelle lors du script de reset | Appel explicite à `init_db()` en début de script pour forcer l'exécution de `_run_migrations()` |
| Tests FastAPI route + SQLite in-memory : erreur « no such table: season_overrides » | `StaticPool` + `check_same_thread=False` pour que les threads TestClient partagent la même DB in-memory |
| Nommage incohérent des fichiers après transfert (renommage CineOrg dans storage) | Script `reset_the_big_c.py` déplace + renomme au pattern scene `The.Big.C.SxxEyy.mkv` lors du mv vers downloads |

## Next Phase Readiness

**Ready:**
- Socle override DB réutilisable pour d'autres cas de divergence canon/local (ex : renumérotation de saisons)
- Pattern AnomalyDetector réutilisable pour d'autres détections post-workflow
- Flag `is_extra` disponible pour piloter l'affichage dans Jellyfin (phase 41) ou dans la bibliothèque web

**Concerns:**
- Titres TVDB absents pour les épisodes `is_extra` : à terme, permettre saisie manuelle du titre (lien avec 42-02 overrides métadonnées)
- Le script `scripts/reset_*.py` est spécifique à The Big C — si d'autres séries présentent le problème, générer un script plus générique

**Blockers:** None

**Commit à créer :** `feat(phase-42-01): détection anomalies hors canon + override acceptance`

---
*Phase: 42-overrides-manuels, Plan: 01*
*Completed: 2026-04-14*
