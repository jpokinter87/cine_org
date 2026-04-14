# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré, un workflow fluide, une suggestion de films, un lecteur distant, des corrections UX, une gestion avancée des données, une réconciliation symlinks/storage robuste, une normalisation structurelle avec détection de doublons, un déploiement production via systemd et des hardlinks de seeding BitTorrent. L'application est stable en v2.0.

## Current Milestone

**v2.1 Lecteurs Externes & Intégrations** (v2.1.0)
Status: 🚧 In Progress
Phases: 1 of 2 complete (50%)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 40 | Lecteur DuneHD | 2/2 | ✅ Complete | 2026-04-14 |
| 41 | Intégration Jellyfin | TBD | 🔵 Ready to plan | - |

### Phase 40: Lecteur DuneHD ✅

Livré 2026-04-14 : nouveau type de profil lecteur "dunehd" déclenchant la lecture sur un media player Dune HD via son API HTTP (`/cgi-bin/do?cmd=start_file_playback`), avec mapping automatique storage → URLs SMB (shares Films / Series TV). Plan 40-01 : backend DuneHDPlayer + schéma profil étendu + dispatcher. Plan 40-02 : UI web de configuration (champs conditionnels mpv/dunehd, validation, badges type). Lecture end-to-end validée sur Dune physique 192.168.1.4 (film + épisode).

### Phase 41: Intégration Jellyfin

Focus: Corriger les volumes Docker pour que Jellyfin accède aux symlinks dans /media/Serveur/Collection. Montage symlinks + cibles (storage) avec les mêmes chemins absolus dans le container. Vérification scan bibliothèque.

## Completed Milestones

<details>
<summary>v2.0 Production & Maintenance Complète — 2026-04-04 (5 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 35 | Maintenance Web Complète | 1/1 | 2026-03-08 |
| 36 | Doublons Symlinks Cross-Genre | 1/1 | 2026-03-13 |
| 37 | Optimisations & Sandbox | 2/2 | 2026-03-20 |
| 38 | Déploiement Production | 1/1 | 2026-04-04 |
| 39 | Hardlinks Seeding | 2/2 | 2026-04-04 |

Archive: `.paul/milestones/v2.0-ROADMAP.md`

</details>

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
*Last updated: 2026-04-14 — Phase 40 Lecteur DuneHD complète (backend + UI config, lecture end-to-end validée), Phase 41 Jellyfin prête à planifier*
