# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-23)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.0 Interface Web — Phase 4 Transfert & Conflits

## Current Position

Milestone: v1.0 Interface Web
Phase: 4 of 5 (Transfert & Conflits) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-23 — Phase 3 complete, transitioned to Phase 4

Progress:
- Milestone: [██████░░░░] 60%
- Phase 4: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Phase 3 loop complete — ready for Phase 4 PLAN]
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

### Deferred Issues
- Code dupliqué matching entre workflow web (routes/workflow.py) et CLI (matching_step.py)

### Blockers/Concerns
None.

### Git State
Last commit: (pending phase commit)
Branch: master

## Session Continuity

Last session: 2026-02-23
Stopped at: Phase 3 complete, ready to plan Phase 4
Next action: /paul:plan for Phase 4 (Transfert & Conflits)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
