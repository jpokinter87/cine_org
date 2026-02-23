# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-23)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.0 Interface Web — Phase 4 complete, prêt pour Phase 5

## Current Position

Milestone: v1.0 Interface Web
Phase: 4 of 5 (Transfert & Conflits) — Complete
Plan: 04-01 complete
Status: Phase complete, transition required
Last activity: 2026-02-23 — Phase 4 UNIFY complete

Progress:
- Milestone: [████████░░] 80%
- Phase 4: [██████████] 100%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — phase transition required]
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
- Silent Rich console pour neutraliser batch_builder en contexte web
- Mode dry-run pour simulation sans risque

### Deferred Issues
- Code dupliqué matching entre workflow web (routes/workflow.py) et CLI (matching_step.py)
- Silent Rich console hack — refactoring batch_builder souhaitable

### Blockers/Concerns
None.

### Git State
Last commit: 8e79f15
Branch: master

## Session Continuity

Last session: 2026-02-23
Stopped at: Phase 4 UNIFY complete
Next action: Phase transition → then Phase 5 planning
Resume file: .paul/phases/04-transfert-conflits/04-01-SUMMARY.md

---
*STATE.md — Updated after every significant action*
