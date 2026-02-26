# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet, d'une interface web fonctionnelle avec données enrichies, un système de gestion des associations TMDB, des données nettoyées, un code refactoré et un workflow fluide. Le prochain objectif est d'améliorer l'expérience utilisateur au quotidien : suggestion de films et lecture à distance.

## Current Milestone

**v1.4 Expérience Utilisateur** (v1.4.0)
Status: Complete
Phases: 2 of 2 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 15 | Que Regarder Ce Soir | 2/2 | Complete | 2026-02-26 |
| 16 | Lecteur Distant | 2/2 | Complete | 2026-02-26 |

## Phase Details

### Phase 15: Que Regarder Ce Soir

**Goal:** Ajouter une fonctionnalité "Surprends-moi" pour suggérer un film à regarder, avec tags "déjà vu" et notes étoiles
**Depends on:** v1.3 (bibliothèque avec métadonnées riches)
**Research:** Possible (algorithme de suggestion, UX du wizard)

**Scope:**
- Tag "déjà vu" en DB (toggle depuis la fiche film)
- Note personnelle en étoiles (1-5) depuis la fiche film
- Page/bouton "Surprends-moi" avec filtres optionnels (genre, durée dispo, humeur)
- Algorithme de suggestion basé sur la bibliothèque (exclut "déjà vu" sauf bonne note)
- Bouton d'accès rapide sur la page d'accueil (4ème bouton)

**Plans:** TBD (defined during /paul:plan)

### Phase 16: Lecteur Distant

**Goal:** Rendre le lecteur vidéo configurable (programme et machine cible) pour lancer la lecture à distance via SSH
**Depends on:** Phase 15 (le lecteur peut être lancé depuis la suggestion)
**Research:** Likely (mécanisme SSH, compatibilité Windows/Linux/Mac)

**Scope:**
- Configuration du lecteur : choix du programme (mpv, vlc, autre exécutable)
- Configuration de la machine cible : locale (défaut) ou distante (IP/hostname LAN)
- Lancement distant via SSH avec authentification par clé
- Page de configuration enrichie avec paramètres lecteur
- Documentation prérequis SSH (activation OpenSSH Server sur Windows)

**Plans:** TBD (defined during /paul:plan)

## Completed Milestones

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
*Last updated: 2026-02-26 — v1.4 complete (Phase 16)*
