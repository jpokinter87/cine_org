# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, et d'un système de gestion des associations TMDB (correction manuelle, détection automatique, tableau de bord qualité). Le prochain objectif est de consolider la qualité du code et des données, et de fluidifier le parcours utilisateur.

## Current Milestone

**v1.3 Qualité & Fluidité** (v1.3.0)
Status: Complete
Phases: 3 of 3 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 12 | Dette Technique Données | 2/2 | Complete | 2026-02-25 |
| 13 | Refactoring Code | 2/2 | Complete | 2026-02-25 |
| 14 | Workflow Fluide | 1/1 | Complete | 2026-02-25 |

## Phase Details

### Phase 12: Dette Technique Données

**Goal:** Combler les lacunes de données accumulées : films sans file_path, métadonnées techniques manquantes, tri accents, titres épisodes
**Depends on:** v1.2 (pipeline métadonnées techniques en place)
**Research:** Unlikely (commandes existantes, algorithmes connus)

**Scope:**
- Enrichissement batch file_path pour les 1307 films manquants
- Extraction métadonnées techniques (résolution, codecs) pour les 443 films concernés
- Normalisation du tri alphabétique : accents, caractères spéciaux, articles
- Nettoyage caractère invisible (ex: "Zoé, mon amie morte")
- Enrichissement titres épisodes manquants (83.3%)

**Plans:** TBD (defined during /paul:plan)

### Phase 13: Refactoring Code

**Goal:** Améliorer la maintenabilité du code sans changer le comportement visible
**Depends on:** Phase 12 (données stabilisées avant refactoring)
**Research:** Unlikely (refactoring pur)

**Scope:**
- Extraction library.py (~650 lignes) en modules dédiés
- Dédoublonnage du code matching entre workflow web et CLI
- Fix du test cassé test_auto_repair_multi_season

**Plans:** TBD (defined during /paul:plan)

### Phase 14: Workflow Fluide

**Goal:** Fluidifier l'enchaînement des étapes du workflow web (scan → validation → transfert)
**Depends on:** Phase 13 (code refactoré et stable)
**Research:** Unlikely (amélioration UX sur patterns HTMX existants)

**Scope:**
- Si tout auto-validé → redirection directe vers l'onglet transfert
- Si validation manuelle nécessaire → redirection vers validation
- Après validation complète → proposition/redirection vers transfert
- Compatibilité avec navigation manuelle (pas de régression)

**Plans:** TBD (defined during /paul:plan)

## Completed Milestones

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
*Last updated: 2026-02-25 — Phase 14 complete, v1.3 milestone complete*
