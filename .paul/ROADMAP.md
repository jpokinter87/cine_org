# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet et d'une interface web fonctionnelle. Le prochain objectif est l'enrichissement des données (crédits, ratings, IMDB IDs) et l'amélioration des fiches détaillées dans l'interface web.

## Milestones

### v1.0 Interface Web — Complete (2026-02-23)

5 phases : Foundation Web, Validation Visuelle, Orchestration Workflow, Transfert & Conflits, Bibliothèque & Maintenance.

---

## Current Milestone

**v1.1 Enrichissement Données** (v1.1.0)
Status: In Progress
Phases: 2 of 3 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 6 | Enrichissement Films | 1/1 | Complete | 2026-02-23 |
| 7 | Enrichissement Séries | 1/1 | Complete | 2026-02-23 |
| 8 | Fiches Détaillées Enrichies | TBD | Not started | - |

## Phase Details

### Phase 6: Enrichissement Films

**Goal:** Enrichir les données films en base : crédits (réalisateur, acteurs), ratings (IMDB/TMDB), IMDB IDs
**Depends on:** v1.0 (bibliothèque films peuplée)
**Research:** Unlikely (commandes enrich-* CLI existantes, TMDB API câblée)

**Scope:**
- Exécution et fiabilisation des commandes `enrich-movies-credits`, `enrich-ratings`, `enrich-imdb-ids`
- Correction des éventuels bugs ou limitations (rate limiting, données manquantes)
- Vérification de la couverture : % de films avec crédits, ratings, IMDB IDs

**Plans:** TBD (defined during /paul:plan)

### Phase 7: Enrichissement Séries

**Goal:** Enrichir les données séries en base : crédits (créateurs, acteurs), ratings, épisodes enrichis
**Depends on:** Phase 6 (patterns d'enrichissement validés)
**Research:** Unlikely (commande enrich-series existante, TMDB TV API câblée)

**Scope:**
- Exécution et fiabilisation de `enrich-series` pour crédits et ratings
- Enrichissement des épisodes individuels (titres, descriptions si disponibles)
- Vérification de la couverture : % de séries avec crédits, ratings

**Plans:** TBD (defined during /paul:plan)

### Phase 8: Fiches Détaillées Enrichies

**Goal:** Améliorer les fiches détaillées web pour exploiter les données enrichies
**Depends on:** Phases 6 et 7 (données enrichies disponibles)
**Research:** Unlikely

**Scope:**
- Acteurs et réalisateurs cliquables dans les fiches (filtre par personne)
- Affichage des ratings (IMDB + TMDB) avec badges visuels
- Liens vers les pages IMDB/TMDB externes
- Amélioration de la grille bibliothèque (badges rating, indicateurs enrichissement)

**Plans:** TBD (defined during /paul:plan)

---
*Roadmap created: 2026-02-23*
*Last updated: 2026-02-23 — v1.1 milestone created*
