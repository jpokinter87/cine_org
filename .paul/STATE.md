# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.5 Polish & Corrections UX — Phase 18

## Current Position

Milestone: v1.5 Polish & Corrections UX
Phase: 18 of 19 — Ré-association Transfert — Not started
Plan: None yet
Status: Ready for /paul:plan
Last activity: 2026-02-26 — Phase 17 complete, transition done

Progress:
- v1.5: [███░░░░░░░] 33% (1/3 phases)
- Phase 18: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for new plan]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- SSH BatchMode=yes + ConnectTimeout=5 (erreurs rapides et claires)
- Route series/play cherche le premier épisode (S01E01) avec fichier

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)
- Atiye / The Gift : deux tvdb_id distincts (372912/433737) pour la même série — à traiter Phase 18

### Blockers/Concerns
None.

### Bug Fixes (cette session)
- QueuePool exhaustion dans batch_builder.py : repositories instanciés hors boucle (fix appliqué, à commiter)

### Git State
Last commit: 87d8d02 feat(16-lecteur-distant): lecteur configurable + profils nommés — phase complete
Branch: master
Uncommitted: Phase 17 + fix batch_builder.py

## Session Continuity

Last session: 2026-02-26
Stopped at: Phase 17 complete, transition done
Next action: Run /paul:plan for Phase 18 or commit Phase 17 changes
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
