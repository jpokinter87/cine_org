# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-25)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.3 Qualité & Fluidité — Phase 13 next

## Current Position

Milestone: v1.3 Qualité & Fluidité
Phase: 13 of 14 — Refactoring Code
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-25 — Phase 12 complete, transitioned to Phase 13

Progress:
- v1.3: [███░░░░░░░] 33%
- Phase 13: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for next PLAN]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Enrichissement séries via TMDB (pas TVDB)
- Filtre personne via LIKE sur director + cast_json
- SSE pour opérations longues + cache fichier persistant 24h
- data-* attributes + addEventListener au lieu de onclick (échappement HTML)
- Pipeline workflow propage toutes les métadonnées techniques
- Ligatures traitées par expansion explicite (œ→oe, æ→ae)
- Recherche SQL via OR sur variantes (contourne limitation SQLite LIKE unicode)
- link-movies passe 2 : match exact titre+année sur fichiers storage/
- Renommage symlinks épisodes reporté (risque médiacenter)

### Deferred Issues
- Code dupliqué matching entre workflow web et CLI → Phase 13
- Routes library.py grossit (~650 lignes) → Phase 13
- Test pré-existant test_auto_repair_multi_season en échec → Phase 13
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres

### Blockers/Concerns
None.

### Git State
Last commit: 568ea93
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: Phase 12 complete, ready to plan Phase 13
Next action: /paul:plan for Phase 13
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
