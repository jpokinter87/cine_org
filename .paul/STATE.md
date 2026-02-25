# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-24)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.2 Gestion Associations — Phase 10 + 9b complete, Phase 11 next

## Current Position

Milestone: v1.2 Gestion Associations
Phase: 10 of 11 (+ 9b hors-série) — Complete
Plan: 10-01 + 9b-01 complete
Status: Ready for Phase 11
Last activity: 2026-02-25 — Phase 9b unified, pipeline métadonnées corrigé

Progress:
- v1.2: [██████░░░░] 67% (2/3 phases + 1 hors-série)
- Phase 9b: [██████████] 100%
- Phase 10: [██████████] 100%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — Phase 9b + 10 done]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Enrichissement séries via TMDB (pas TVDB)
- Filtre personne via LIKE sur director + cast_json
- Durée fichier via mediainfo + résolution symlink (pas la valeur DB)
- Indicateurs confiance : durée (films), saisons/épisodes (séries)
- Dialog custom pour confirmation ré-association (pas confirm() natif)
- SSE pour opérations longues (scan qualité) + cache fichier persistant 24h
- Comparaison titre avec original_title pour réduire faux positifs
- Durée en pourcentage (30%/15%) au lieu de valeurs absolues
- data-* attributes + addEventListener au lieu de onclick (échappement HTML)
- Tri décroissant par défaut (meilleurs en premier)
- Séries documentaires exclues du périmètre
- Pipeline workflow propage désormais toutes les métadonnées techniques

### Deferred Issues
- Code dupliqué matching entre workflow web et CLI
- Silent Rich console hack — refactoring batch_builder souhaitable
- Titres épisodes manquants (83.3%)
- 1307 films sans file_path (enrichissement batch à planifier)
- Routes library.py grossit (~650 lignes) — extraction module dédiée envisageable

### Blockers/Concerns
None.

### Git State
Last commit: 98260bd (push master à jour)
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: Phase 9b UNIFY done + pipeline métadonnées corrigé
Next action: /paul:plan for Phase 11 (Tableau de Bord Qualité)
Resume file: .paul/phases/09b-metadonnees-techniques/09b-01-SUMMARY.md

---
*STATE.md — Updated after every significant action*
