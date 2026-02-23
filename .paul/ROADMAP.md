# Roadmap: CineOrg

## Overview

CineOrg dispose d'un CLI complet et fonctionnel. La prochaine étape majeure est la création d'une interface web permettant une validation visuelle des candidats (jaquettes, synopsis, acteurs) pour les titres équivoques, en complément du CLI existant.

## Current Milestone

**v1.0 Interface Web** (v1.0.0)
Status: In progress
Phases: 3 of 5 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation Web | 1/1 | Complete | 2026-02-23 |
| 2 | Validation Visuelle | 2/2 | Complete | 2026-02-23 |
| 3 | Orchestration Workflow | 1/1 | Complete | 2026-02-23 |
| 4 | Transfert & Conflits | TBD | Not started | - |
| 5 | Bibliothèque & Maintenance | TBD | Not started | - |

## Phase Details

### Phase 1: Foundation Web

**Goal:** Mettre en place l'application FastAPI, le wiring DI, le layout Jinja2 de base, les assets statiques et un point d'entrée serveur web
**Depends on:** Nothing (first phase)
**Status:** Complete (2026-02-23)

**Plans:**
- [x] 01-01: Setup FastAPI app + Container DI + layout de base + page d'accueil

### Phase 2: Validation Visuelle

**Goal:** Reproduire et améliorer le flux de validation CLI avec affichage visuel des candidats (jaquettes, synopsis, cast, année, score)
**Depends on:** Phase 1 (app FastAPI fonctionnelle)
**Research:** Unlikely (services ValidationService/MatcherService déjà prêts pour web)

**Scope:**
- Liste des fichiers en attente de validation (pending)
- Affichage enrichi des candidats avec jaquettes TMDB/TVDB
- Actions : valider, rejeter, skip, recherche manuelle, recherche par ID
- Pagination des candidats
- Affichage du score avec code couleur

**Plans:**
- [x] 02-01: Routes API + templates validation pending
- [x] 02-02: Interactions HTMX validation/rejet/recherche

### Phase 3: Orchestration Workflow

**Goal:** Permettre de lancer le workflow complet (scan → matching → auto-validation) depuis l'interface web avec suivi de progression
**Depends on:** Phase 2 (validation visuelle pour la partie manuelle)
**Research:** Unlikely (WorkflowService async existant)

**Scope:**
- Déclenchement du workflow depuis le web
- Suivi de progression en temps réel (SSE ou polling HTMX)
- Affichage des résultats d'auto-validation
- Gestion des erreurs et annulation

**Status:** Complete (2026-02-23)

**Plans:**
- [x] 03-01: Lancement workflow + suivi progression SSE + cascade auto-validation séries

### Phase 4: Transfert & Conflits

**Goal:** Interface web pour le résumé batch, la confirmation de transfert et la résolution de conflits
**Depends on:** Phase 3 (workflow fournit les fichiers validés à transférer)
**Research:** Unlikely (TransfererService existant)

**Scope:**
- Résumé batch visuel (arborescence des transferts prévus)
- Confirmation et exécution du transfert
- Détection et résolution de conflits (doublon, collision de noms)
- Affichage comparatif des fichiers en conflit

**Plans:**
- [ ] 04-01: Résumé batch + transfert + résolution conflits

### Phase 5: Bibliothèque & Maintenance

**Goal:** Navigation dans la vidéothèque et outils de maintenance accessibles via le web
**Depends on:** Phase 1 (app de base suffisante)
**Research:** Unlikely

**Scope:**
- Navigation films/séries avec filtres (genre, année, note)
- Détail d'un film/série (métadonnées, jaquette, fichiers associés)
- Réparation des symlinks cassés
- Vérification d'intégrité
- Cleanup / nettoyage

**Plans:**
- [ ] 05-01: Navigation bibliothèque films/séries
- [ ] 05-02: Outils maintenance (repair, check, cleanup)

---
*Roadmap created: 2026-02-23*
*Last updated: 2026-02-23 — Phase 3 complete*
