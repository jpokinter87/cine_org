# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-23)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.0 Interface Web — Phase 5 Plan 02 complete, ready for next plan

## Current Position

Milestone: v1.0 Interface Web
Phase: 5 of 5 (Bibliothèque & Maintenance) — In Progress
Plan: 05-03 created, awaiting approval
Status: PLAN created, ready for APPLY
Last activity: 2026-02-23 — Created .paul/phases/05-bibliotheque-maintenance/05-03-PLAN.md

Progress:
- Milestone: [█████████░] 93%
- Phase 5: [██████░░░░] 66% (2/3 plans)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ○        ○     [Plan created, awaiting approval]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Lifespan DI pattern pour initialisation Container dans FastAPI
- deps.py pour partage des templates (évite imports circulaires)
- Enrichissement API synchrone dans les routes (acceptable pour <100 pending)
- Fragments HTMX + HX-Redirect pour les actions POST
- Dialogue custom pour actions destructives (overlay CSS)
- Pagination côté serveur pour les candidats (?page=N)
- SSE via StreamingResponse + EventSource pour progression workflow temps réel
- WorkflowProgress class comme état partagé (asyncio.Task ↔ SSE)
- Cascade auto-validation séries : valider 1 épisode → auto-valide les autres (même candidat TVDB)
- Services individuels réutilisés dans le web (pas WorkflowService couplé Rich)
- TransferProgress avec asyncio.Event pour pause/resume conflit
- Silent Rich console hack — refactoring batch_builder souhaitable
- Mode dry-run pour simulation sans risque
- HTMX 2.0.4 : form hx-get avec hx-trigger centralisé (pas hx-get par select)
- year param en str avec conversion manuelle (FastAPI parse "" comme erreur int)
- Rating : IMDb prioritaire, fallback TMDB (fonction _best_rating)
- Enrichissement séries via TMDB TV API (search_tv + get_tv_details avec credits)
- Director/cast ajoutés aux modèles MovieModel et SeriesModel
- htmx.config.refreshOnHistoryMiss = true pour navigation arrière navigateur
- Normalisation titres pour résolution fichiers (strip caractères spéciaux)
- Form POST classique pour configuration (pas HTMX — sauvegarde unique avec redirect)
- database_url en lecture seule dans la page config

### Deferred Issues
- Code dupliqué matching entre workflow web (routes/workflow.py) et CLI (matching_step.py)
- Silent Rich console hack — refactoring batch_builder souhaitable
- Director/cast absents pour ~5650 films et ~938 séries (nécessite exécution des commandes enrich-*)
- Rendre les noms d'acteurs et réalisateurs cliquables dans les fiches détaillées

### Blockers/Concerns
None.

### Git State
Last commit: 8292787 (populate-series)
Branch: master
Uncommitted: plans 05-01 + 05-02 (library + enrichment + config)

## Session Continuity

Last session: 2026-02-23
Stopped at: Plan 05-03 created
Next action: Review and approve plan, then run /paul:apply
Resume file: .paul/phases/05-bibliotheque-maintenance/05-03-PLAN.md

---
*STATE.md — Updated after every significant action*
