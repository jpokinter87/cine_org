# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.4 Expérience Utilisateur — Complete

## Current Position

Milestone: v1.4 Expérience Utilisateur — Complete
Phase: 16 of 16 — Lecteur Distant — Complete
Plan: 16-02 complete (profils lecteur)
Status: Milestone v1.4 complete
Last activity: 2026-02-26 — Phase 16 complete, v1.4 milestone closed

Progress:
- v1.4: [██████████] 100% (2/2 phases)
- Phase 16: [██████████] 100% (2/2 plans)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone v1.4 closed]
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
- Suggestion : random parmi éligibles, pas de ML — simple et efficace
- Lecteur distant : SSH + mapping de chemins (pas de streaming)
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- SSH BatchMode=yes + ConnectTimeout=5 (erreurs rapides et claires)
- extra=ignore dans Settings pour tolérer les anciens champs player_* du .env

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Ré-association in extremis depuis la page transfert (cases à cocher pour renvoyer en validation)
- Bouton Visionner sur les fiches du mode Surprends-moi
- Page /config trop longue : restructurer avec sous-sections pliables (accordéon)
- Test lecteur distant sur machine Windows (stand-by)

### Blockers/Concerns
None.

### Git State
Last commit: 187006e feat(16-lecteur-distant): lecteur configurable + profils nommés — phase complete
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: v1.4 milestone complete
Next action: /paul:complete-milestone or plan next milestone
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
