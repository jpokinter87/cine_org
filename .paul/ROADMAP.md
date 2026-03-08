# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré, un workflow fluide, une suggestion de films, un lecteur distant, des corrections UX, une gestion avancée des données, une réconciliation symlinks/storage robuste, et une normalisation structurelle avec détection de doublons. L'application est stable en v1.9.

## Current Milestone

**v2.0 Production & Maintenance Complète** (v2.0.0)
Status: 🚧 In Progress
Phases: 0 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 35 | Maintenance Web Complète | 2 | Planning | - |
| 36 | Doublons Symlinks Cross-Genre | TBD | Not started | - |
| 37 | Déploiement Production | TBD | Not started | - |
| 38 | Intégration Jellyfin | TBD | Not started | - |

### Phase 35: Maintenance Web Complète

Focus: Opérations maintenance depuis le web (cleanup, repair, etc.), résultats détaillés fichier par fichier, gestion sandbox (liste, suppression définitive). La sortie détaillée est web-only.

### Phase 36: Doublons Symlinks Cross-Genre

Focus: Détection des symlinks dans video/ pointant vers le même fichier physique mais classés dans des genres différents (ex: Comédie dramatique dans Comédie ET Drame). Nettoyage selon le genre prioritaire (GENRE_HIERARCHY). Fonction générale.

### Phase 37: Déploiement Production

Focus: Service systemd pour uvicorn, workflow git dev→serveur (push/pull), configuration paths/ports/logs. Documentation déploiement. Permettre de continuer le développement sur la machine de dev.

### Phase 38: Intégration Jellyfin

Focus: Corriger les volumes Docker pour que Jellyfin accède aux symlinks dans /media/Serveur/Collection. Montage symlinks + cibles (storage) avec les mêmes chemins absolus dans le container. Vérification scan bibliothèque.

## Completed Milestones

<details>
<summary>v1.9 Normalisation & Intégration Jellyfin — 2026-03-07 (5 phases, 1 abandoned)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 29 | Films Multi-Parties | 1/1 | 2026-03-01 |
| 30 | Normalisation Répertoires Séries | 2/2 | 2026-03-01 |
| 31 | Détection de Doublons | 2/2 | 2026-03-01 |
| 32 | ~~NFO & Artwork Sidecar Jellyfin~~ | - | Abandoned |
| 33 | Overlays Qualité Web UI | 1/1 | 2026-03-07 |
| 34 | Détection Doublons au Transfert | 1/1 | 2026-03-04 |

Archive: `.paul/milestones/v1.9-ROADMAP.md`

</details>

<details>
<summary>v1.8 Robustesse Workflow & Corrections UX — 2026-03-01 (3 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 26 | Corrections UX Mineures | 1/1 | 2026-02-28 |
| 27 | Performance & Robustesse Matching | 1/1 | 2026-02-28 |
| 28 | Films Spéciaux | 1/1 | 2026-03-01 |

Archive: `.paul/milestones/v1.8-ROADMAP.md`

</details>

<details>
<summary>v1.7 Fiabilité & Ergonomie Bibliothèque — 2026-02-28 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 24 | Refonte UX Filtres Bibliothèque | 1/1 | 2026-02-28 |
| 25 | Réconciliation Symlinks/Storage | 1/1 | 2026-02-28 |

Archive: `.paul/milestones/v1.7-ROADMAP.md`

</details>

<details>
<summary>v1.6 Gestion & Qualité de Données — 2026-02-28 (4 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 20 | Améliorations Navigation & Affichage | 1/1 | 2026-02-27 |
| 21 | Résolution Données Manquantes | 2/2 | 2026-02-27 |
| 22 | Suppression depuis la Bibliothèque | 1/1 | 2026-02-27 |
| 23 | Lectures Simultanées | 1/1 | 2026-02-28 |

Archive: `.paul/milestones/v1.6-ROADMAP.md`

</details>

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
*Last updated: 2026-03-07 — Milestone v2.0 created*
