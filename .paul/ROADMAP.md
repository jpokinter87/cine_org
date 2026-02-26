# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré, un workflow fluide, une suggestion de films et un lecteur distant. Le prochain objectif est de corriger les irritants UX identifiés pendant l'utilisation quotidienne.

## Current Milestone

**v1.5 Polish & Corrections UX** (v1.5.0)
Status: In Progress
Phases: 1 of 3 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 17 | Visionner Surprends-moi | 1 | Complete | 2026-02-26 |
| 18 | Ré-association Transfert | 2 | Planning | - |
| 19 | Config Accordéon | TBD | Not started | - |

## Phase Details

### Phase 17: Visionner Surprends-moi

**Goal:** Ajouter le bouton Visionner sur les fiches de suggestion de la page Surprends-moi
**Depends on:** Phase 16 (système de profils lecteur)

**Scope:**
- Bouton play identique à celui des fiches détail (utilise _play_button_html existant)
- Lancement de la lecture directement depuis la page suggestion sans la quitter
- Polling du statut de lecture (identique aux fiches détail)

**Plans:** 1 plan (complete)

### Phase 18: Ré-association Transfert

**Goal:** Permettre de corriger les auto-validations erronées depuis la page transfert ET la page validation
**Depends on:** Aucun

**Scope:**
- Plan 01 : Bouton "Renvoyer en validation" sur chaque fichier de la page transfert + service reset_to_pending
- Plan 02 : Section "Auto-validés" sur la page validation avec bouton "Revalider"
- Le fichier renvoyé retourne en statut pending pour revalidation manuelle

**Plans:** 2 plans (01: transfert, 02: validation)

### Phase 19: Config Accordéon

**Goal:** Restructurer la page /config avec des sous-sections pliables pour réduire le scroll
**Depends on:** Aucun

**Scope:**
- Chaque section (Répertoires, Base de données, Clés API, Traitement, Journalisation, Lecteur) est pliable/dépliable
- CSS pur (details/summary) ou JS minimal
- Section active ouverte par défaut, les autres fermées
- Cohérence avec le thème sombre existant

**Plans:** TBD (defined during /paul:plan)

## Completed Milestones

<details>
<summary>v1.4 Expérience Utilisateur — 2026-02-26 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 15 | Que Regarder Ce Soir | 2/2 | 2026-02-26 |
| 16 | Lecteur Distant | 2/2 | 2026-02-26 |

Archive: `.paul/milestones/v1.4-ROADMAP.md`

</details>

<details>
<summary>v1.3 Qualité & Fluidité — 2026-02-25 (3 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 12 | Dette Technique Données | 2/2 | 2026-02-25 |
| 13 | Refactoring Code | 2/2 | 2026-02-25 |
| 14 | Workflow Fluide | 1/1 | 2026-02-25 |

Archive: `.paul/milestones/v1.3-ROADMAP.md`

</details>

<details>
<summary>v1.2 Gestion Associations — 2026-02-25 (4 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 9 | Correction Manuelle Associations | 1/1 | 2026-02-24 |
| 9b | Métadonnées Techniques & Filtres Avancés | 1/1 | 2026-02-25 |
| 10 | Détection Automatique Erreurs | 1/1 | 2026-02-25 |
| 11 | Tableau de Bord Qualité | 1/1 | 2026-02-25 |

Archive: `.paul/milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>v1.1 Enrichissement Données — 2026-02-24 (3 phases)</summary>

3 phases : Enrichissement Films, Enrichissement Séries, Fiches Détaillées Enrichies.

</details>

<details>
<summary>v1.0 Interface Web — 2026-02-23 (5 phases)</summary>

5 phases : Foundation Web, Validation Visuelle, Orchestration Workflow, Transfert & Conflits, Bibliothèque & Maintenance.

</details>

---
*Roadmap created: 2026-02-23*
*Last updated: 2026-02-26 — Phase 17 complete*
