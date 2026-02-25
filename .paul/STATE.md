# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-25)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.2 Gestion Associations — COMPLETE

## Current Position

Milestone: v1.2 Gestion Associations — COMPLETE
Phase: 11 of 11 — Tableau de Bord Qualité — Complete
Plan: 11-01 complete
Status: Milestone complete, ready for next milestone
Last activity: 2026-02-25 — Phase 11 unified, v1.2 complete

Progress:
- v1.2: [██████████] 100% (4/4 phases)
- Phase 11: [██████████] 100% (1/1 plans)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Phase 11 — loop complete, milestone complete]
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
- Métriques couverture SQL COUNT à la volée (pas de cache dédié)
- Dashboard qualité : layout 2 colonnes (couverture + sidebar)

### Deferred Issues
- Code dupliqué matching entre workflow web et CLI
- Silent Rich console hack — refactoring batch_builder souhaitable
- Titres épisodes manquants (83.3%)
- 1307 films sans file_path (enrichissement batch à planifier)
- Routes library.py grossit (~650 lignes) — extraction module dédiée envisageable
- Tri bibliothèque : les caractères accentués/spéciaux sont mal triés (placés en fin au lieu d'être normalisés). Exemples : "...Et pour quelques dollars de plus" devrait être sous E, "'Ohana" et "Ôtez-moi d'un doute" sous O. Cas particulier : "Zoé, mon amie morte" contient un caractère invisible avant le Z (à nettoyer en DB)
- Test pré-existant test_auto_repair_multi_season en échec (non lié aux phases récentes)

### Blockers/Concerns
None.

### Git State
Last commit: pending (phase 11 commit à créer)
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: v1.2 milestone complete
Next action: /paul:complete-milestone (or /paul:milestone for next)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
