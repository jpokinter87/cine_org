# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-27)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.6 Gestion & Qualité de Données

## Current Position

Milestone: v1.6 Gestion & Qualité de Données
Phase: 22 of 4 (Suppression depuis la Bibliothèque) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-27 — Phase 21 complete, transitioned to Phase 22

Progress:
- v1.6: [█████░░░░░] 50%
- Phase 20: [██████████] 100% ✓
- Phase 21: [██████████] 100% ✓

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for next PLAN]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- NullPool pour SQLite — supprime le QueuePool qui s'épuisait avec providers.Factory
- Cascade inverse séries : renvoyer un épisode renvoie tous les épisodes du même candidat
- Dialogues custom overlay au lieu de confirm() natif — cohérence charte graphique
- Version footer dynamique via tomllib dans deps.py
- Suppression : corbeille provisoire réversible, suppression physique uniquement au vidage définitif
- Seuil fuzzy 0.85 validé pour link-movies et enrich-tvdb-ids
- Index mémoire par année pour matching batch (pas de requête DB par symlink)
- Recherche TVDB multi-titre : FR→original→racine (tiret) + nettoyage année

### Deferred Issues
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)
- ~10-12 films récupérables via normalisation de ponctuation (`:·?` → `-...`)
- 197 films sans fichier physique correspondant — irrésoluble par matching
- Outil pour lister facilement les épisodes/séries avec données manquantes (correction manuelle)
- 285 épisodes sans titre (limites TVDB : séries anciennes, numérotation spéciale)
- 5 séries sans tvdb_id (Dahmer="Monstre" sur TVDB, Ed Gein/Playgame/Suspect pas sur TVDB, Punisher=homonyme)

### Blockers/Concerns
None.

### Git State
Last commit: 8c1f466 feat(21-donnees-manquantes): link-movies amélioré
Branch: master
Uncommitted: enrich-tvdb-ids (plan 21-02)

## Session Continuity

Last session: 2026-02-27
Stopped at: Phase 21 complete, ready to plan Phase 22
Next action: /paul:plan for Phase 22 (Suppression depuis la Bibliothèque)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
