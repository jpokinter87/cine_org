# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.5 Polish & Corrections UX — Phase 19

## Current Position

Milestone: v1.5 Polish & Corrections UX
Phase: 19 of 19 — Config Accordéon — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-26 — Phase 18 complete, transitioned to Phase 19

Progress:
- v1.5: [██████░░░░] 67% (2/3 phases)
- Phase 19: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready to plan Phase 19]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- Route series/play cherche le premier épisode (S01E01) avec fichier
- NullPool pour SQLite — supprime le QueuePool qui s'épuisait avec providers.Factory
- Cascade inverse séries : renvoyer un épisode renvoie tous les épisodes du même candidat
- Dialogues custom overlay au lieu de confirm() natif — cohérence charte graphique

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)

### Blockers/Concerns
None.

### Git State
Last commit: (pending — phase 18 changes to commit)
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: Phase 18 complete, ready to plan Phase 19
Next action: /paul:plan for Phase 19
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
