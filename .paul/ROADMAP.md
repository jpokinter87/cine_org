# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré, un workflow fluide, une suggestion de films, un lecteur distant, des corrections UX, une gestion avancée des données, et une réconciliation symlinks/storage robuste. L'application est stable en v1.8. Le prochain objectif est la normalisation structurelle et l'intégration Jellyfin.

## Current Milestone

**v1.9 Normalisation & Intégration Jellyfin** (v1.9.0)
Status: 🚧 In Progress
Phases: 4 of 6 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 29 | Films Multi-Parties | 1/1 | ✅ Complete | 2026-03-01 |
| 30 | Normalisation Répertoires Séries | 2/2 | ✅ Complete | 2026-03-01 |
| 31 | Détection de Doublons | 2/2 | ✅ Complete | 2026-03-01 |
| 32 | ~~NFO & Artwork Sidecar Jellyfin~~ | - | ❌ Abandoned | 2026-03-01 |
| 33 | Overlays Qualité Web UI | TBD | Not started | - |
| 34 | Détection Doublons au Transfert | 1/1 | ✅ Complete | 2026-03-04 |

### Phase 29: Films Multi-Parties

Focus: Corriger le renamer qui génère le même nom pour Partie 1 et Partie 2 → écrasement au transfert. Ajouter `part` dans ParsedInfo/ParsedFilename, l'intégrer au renamer.

### Phase 30: Normalisation Répertoires Séries

Focus: Renommer `Séries` → `Series` (sans accents) sur NAS et symlinks pour compatibilité Jellyfin. Restructurer les sous-dossiers (TV, Animation avec Courts, Mangas). Migrer le code source (53+ fichiers), les file_path en DB, et les fichiers physiques.

### Phase 31: Détection de Doublons

Focus: Commande check-duplicates groupant par TMDB ID, comparant qualité (résolution, codec, taille). Whitelist pour doublons volontaires. Vue web avec actions.

### Phase 32: ~~NFO & Artwork Sidecar Jellyfin~~ (Abandonné)

Abandonné après prototype : Jellyfin scrape très bien TMDB tout seul. Les fichiers sidecar (NFO + poster + fanart) quadruplent le nombre d'entrées par répertoire pour un bénéfice marginal. Code reverté.

### Phase 33: Overlays Qualité Web UI

Focus: Badges visuels CSS sur les posters (résolution, codec, langue). Données déjà en base, purement frontend.

### Phase 34: Détection Doublons au Transfert

Focus: Détecter les titres similaires existants avant le transfert (séries et films). Dialogue de comparaison avec métadonnées techniques, présélection qualité, choix utilisateur (garder ancien/nouveau/les deux avec sandbox). Parité CLI/Web. Remplace le mécanisme CLI existant insatisfaisant.

## Completed Milestones

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
*Last updated: 2026-03-04 — Phase 34 complete*
