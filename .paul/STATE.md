# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.4 Expérience Utilisateur — Phase 15 complete

## Current Position

Milestone: v1.4 Expérience Utilisateur
Phase: 15 of 16 — Que Regarder Ce Soir — Complete
Plan: 15-02 complete (phase done)
Status: Ready for next PLAN (Phase 16)
Last activity: 2026-02-26 — Phase 15 UNIFY + transition complete

Progress:
- v1.4: [█████░░░░░] 50% (1/2 phases)
- Phase 15: [██████████] 100% (2/2 plans)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete - ready for next PLAN]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Ligatures traitées par expansion explicite (œ→oe, æ→ae)
- Recherche SQL via OR sur variantes (contourne limitation SQLite LIKE unicode)
- Code partagé CLI/web via factory functions standalone dans src/services/workflow/
- Package library/ avec sous-routers FastAPI pour découpage routes web
- Boutons accès rapide plutôt que redirections auto (respect du rythme utilisateur)
- Extension watched/rating aux séries (cohérence UX films + séries)
- Badge vu pastille verte + badge type en conteneur flex (évite chevauchement)
- Routes toggle/rate directes dans detail.py (pas via repository)
- Suggestion : random parmi éligibles, pas de ML — simple et efficace
- Filtres auto-submit au changement (onchange) pour UX fluide
- Animation glow ambrée sur bouton Surprends-moi à chaque mouvement souris
- Params formulaire en str avec parsing manuel (évite erreur FastAPI sur chaîne vide)

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Ré-association in extremis depuis la page transfert (cases à cocher pour renvoyer en validation)

### Blockers/Concerns
None.

### Git State
Last commit: pending (phase 15 commit)
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: Phase 15 complete, transition done
Next action: Commit phase 15, then /paul:plan for Phase 16 (Lecteur Distant) or /paul:complete-milestone
Resume file: .paul/phases/15-que-regarder-ce-soir/15-02-SUMMARY.md

---
*STATE.md — Updated after every significant action*
