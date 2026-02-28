# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré, un workflow fluide, une suggestion de films, un lecteur distant et des corrections UX. L'application est stable en v1.5.

## Current Milestone

**v1.6 Gestion & Qualité de Données** (v1.6.0)
Status: Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 20 | Améliorations Navigation & Affichage | 1/1 | Complete | 2026-02-27 |
| 21 | Résolution Données Manquantes | 2/2 | Complete | 2026-02-27 |
| 22 | Suppression depuis la Bibliothèque | 1/1 | Complete | 2026-02-27 |
| 23 | Lectures Simultanées | 1/1 | Complete | 2026-02-28 |

### Phase 20: Améliorations Navigation & Affichage

Focus: Quick wins UX — cartouches accueil cliquables (Films→Biblio Films, Séries→Biblio Séries, En attente→Validation), chemin S01E01 sur fiches séries, dédoublonnage genres (Drame/Drama), tri "récemment ajoutés"
Plans: TBD (defined during /paul:plan)

### Phase 21: Résolution Données Manquantes

Focus: Combler les 1260 films sans file_path (matching fuzzy/normalisation), 367 épisodes sans titres (recherche alternative TVDB), diagnostic métadonnées techniques manquantes (cas "La Zone d'Intérêt")
Plans: TBD (defined during /paul:plan)

### Phase 22: Suppression depuis la Bibliothèque

Focus: Sélection multiple de fiches avec filtres, confirmation obligatoire, corbeille provisoire (consultation, restauration individuelle, vidage définitif), cascade série complète. Suppression physique uniquement au vidage.
Plans: TBD (defined during /paul:plan)

### Phase 23: Lectures Simultanées

Focus: Permettre plusieurs lectures vidéo en parallèle, supprimer la contrainte de profil lecteur unique actif, sessions de lecture indépendantes.
Plans: TBD (defined during /paul:plan)

## Completed Milestones

<details>
<summary>v1.5 Polish & Corrections UX — 2026-02-26 (3 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 17 | Visionner Surprends-moi | 1/1 | 2026-02-26 |
| 18 | Ré-association Transfert | 2/2 | 2026-02-26 |
| 19 | Config Accordéon | 1/1 | 2026-02-26 |

Archive: `.paul/milestones/v1.5-ROADMAP.md`

</details>

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
*Last updated: 2026-02-28 — Phase 23 complete (lectures simultanées + popover profil) — Milestone v1.6 complete*
