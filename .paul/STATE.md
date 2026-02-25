# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-25)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** Awaiting next milestone (v1.2 complete)

## Current Position

Milestone: Awaiting next milestone
Phase: None active
Plan: None
Status: Milestone v1.2 Gestion Associations complete — ready for next
Last activity: 2026-02-25 — Milestone v1.2 completed and archived

Progress:
- v1.2: [██████████] 100% ✓

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Milestone complete - ready for next]
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
- data-* attributes + addEventListener au lieu de onclick (échappement HTML)
- Séries documentaires exclues du périmètre
- Pipeline workflow propage toutes les métadonnées techniques

### Deferred Issues
- Code dupliqué matching entre workflow web et CLI
- Silent Rich console hack — refactoring batch_builder souhaitable
- Titres épisodes manquants (83.3%)
- 1307 films sans file_path (enrichissement batch à planifier)
- Routes library.py grossit (~650 lignes) — extraction module dédiée envisageable
- Tri bibliothèque : caractères accentués/spéciaux mal triés
- Test pré-existant test_auto_repair_multi_season en échec
- 443 films sans métadonnées techniques (enrichissement mediainfo batch)

### Blockers/Concerns
None.

### Git State
Last commit: 054f0f4
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: Milestone v1.2 complete
Next action: /paul:discuss-milestone or /paul:milestone
Resume file: .paul/MILESTONES.md

---
*STATE.md — Updated after every significant action*
