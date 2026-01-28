# Milestone v1.0: MVP CLI Application

**Status:** SHIPPED 2026-01-28
**Phases:** 1-8
**Total Plans:** 17

## Overview

CineOrg est une réécriture complète d'une application de gestion de vidéothèque. Le parcours démarre par les fondations architecturales (hexagonale) pour éviter le couplage CLI/métier de la v1, puis établit l'infrastructure (parsing, APIs, base de données), implémente les services métier avec injection de dépendances, construit progressivement la CLI avec les commandes de traitement et validation, et termine par l'import de la vidéothèque existante avec les outils de maintenance.

## Phases

### Phase 1: Fondations Architecture

**Goal**: Établir l'architecture hexagonale avec séparation stricte domain/application/infrastructure pour garantir la réutilisabilité entre CLI et Web
**Depends on**: Nothing (first phase)
**Requirements**: ARCH-01, ARCH-02, ARCH-03, ARCH-04
**Status**: COMPLETE (2026-01-26)

**Success Criteria** (what must be TRUE):
1. La structure de répertoires domain/application/infrastructure/adapters existe avec __init__.py
2. Le container DI peut injecter des implémentations concrètes pour les ports abstraits
3. La configuration via pydantic-settings charge les variables d'environnement et fichier config
4. Le logging structuré écrit des logs JSON avec rotation et niveaux configurables

Plans:
- [x] 01-01-PLAN.md — Structure hexagonale, entités domain et ports abstraits
- [x] 01-02-PLAN.md — Container DI, configuration pydantic-settings et logging loguru

### Phase 2: Parsing et Scan

**Goal**: Scanner les répertoires de téléchargements et extraire les métadonnées des fichiers vidéo via guessit et mediainfo
**Depends on**: Phase 1
**Requirements**: PARS-01, PARS-02, PARS-03, PARS-04
**Status**: COMPLETE (2026-01-27)

**Success Criteria** (what must be TRUE):
1. Le scan récursif détecte tous les fichiers vidéo dans téléchargements/Films et téléchargements/Séries
2. Guessit extrait correctement titre, année, saison, épisode des noms de fichiers
3. Mediainfo extrait codec, résolution, langues audio, durée des fichiers
4. Le type (film vs série) est détecté automatiquement et corrigé si le fichier est mal placé

Plans:
- [x] 02-01-PLAN.md — Ports parsing, value objects ParsedFilename/MediaType, ScannerService infrastructure
- [x] 02-02-PLAN.md — Adaptateurs GuessitFilenameParser et MediaInfoExtractor avec TDD, intégration DI

### Phase 3: Clients API

**Goal**: Interroger TMDB et TVDB pour rechercher et récupérer les métadonnées films/séries avec gestion robuste du rate limiting
**Depends on**: Phase 1
**Requirements**: API-01, API-02, API-03, API-04, API-05
**Status**: COMPLETE (2026-01-27)

**Success Criteria** (what must be TRUE):
1. Le client TMDB recherche des films par titre et récupère les métadonnées complètes
2. Le client TVDB recherche des séries/épisodes et récupère les métadonnées complètes
3. Le scoring (titre 50% + année 25% + durée 25%) classe les candidats avec seuil 85%
4. Les résultats API sont cachés (24h recherches, 7j détails)
5. Le rate limiting avec retry et backoff exponentiel évite les erreurs 429

Plans:
- [x] 03-01-PLAN.md — Infrastructure cache (diskcache) et retry (tenacity) pour les clients API
- [x] 03-02-PLAN.md — Client TMDB implémentant IMediaAPIClient avec TDD
- [x] 03-03-PLAN.md — Client TVDB implémentant IMediaAPIClient avec authentification JWT et TDD
- [x] 03-04-PLAN.md — MatcherService avec scoring films (50/25/25) et séries (100% titre) via rapidfuzz

### Phase 4: Persistance

**Goal**: Stocker films, séries, épisodes et fichiers en attente dans une base SQLite avec SQLModel
**Depends on**: Phase 1
**Requirements**: DB-01, DB-02, DB-03, DB-04, DB-05
**Status**: COMPLETE (2026-01-27)

**Success Criteria** (what must be TRUE):
1. Les tables films, séries, épisodes existent avec leurs relations
2. La table pending_validation stocke les fichiers en attente de validation manuelle
3. La table trash conserve l'historique des suppressions
4. Les index sur tmdb_id, tvdb_id, title accélèrent les recherches
5. Le hash de fichier est calculé et stocké pour détecter les doublons

Plans:
- [x] 04-01-PLAN.md — Infrastructure database SQLite, modèles SQLModel avec index
- [x] 04-02-PLAN.md — Service hash XXHash, repositories implémentant les ports, intégration DI

### Phase 5: Organisation Fichiers

**Goal**: Renommer les fichiers selon le format standardisé et les organiser dans la structure vidéothèque avec symlinks
**Depends on**: Phase 4
**Requirements**: ORG-01, ORG-02, ORG-03, ORG-04
**Status**: COMPLETE (2026-01-27)

**Success Criteria** (what must be TRUE):
1. Les fichiers sont renommés au format "Titre (Année) Langue Codec Résolution.ext"
2. Les films sont organisés dans stockage/Films/Genre/Lettre/
3. Les séries sont organisées dans stockage/Séries/Lettre/Titre/Saison XX/
4. Les symlinks dans video/ pointent vers les fichiers dans stockage/

Plans:
- [x] 05-01-PLAN.md — Services renommage (RenamerService), organisation (OrganizerService) et scoring qualité (QualityScorerService)
- [x] 05-02-PLAN.md — Service transfert atomique (TransfererService) avec symlinks et intégration DI

### Phase 6: Validation

**Goal**: Valider automatiquement les correspondances avec score >= 85% et permettre la validation manuelle pour les cas ambigus via CLI
**Depends on**: Phase 3, Phase 4
**Requirements**: VALID-01, VALID-02, VALID-03, VALID-04
**Status**: COMPLETE (2026-01-28)

**Success Criteria** (what must be TRUE):
1. Les fichiers avec score >= 85% et résultat unique sont validés automatiquement
2. L'utilisateur peut voir les candidats et sélectionner le bon match via CLI
3. L'utilisateur peut rechercher manuellement par titre ou saisir un ID IMDB/TMDB/TVDB
4. La validation finale batch affiche tous les fichiers avec leurs destinations avant transfert

Plans:
- [x] 06-01-PLAN.md — ValidationService avec logique auto-validation et sélection candidat
- [x] 06-02-PLAN.md — Interface CLI validation interactive avec Rich (cartes candidats, batch, progression)

### Phase 7: CLI Principale

**Goal**: Fournir les commandes CLI pour le workflow principal: scan, traitement, et gestion des fichiers en attente
**Depends on**: Phase 2, Phase 5, Phase 6
**Requirements**: CLI-01, CLI-02, CLI-03
**Status**: COMPLETE (2026-01-28)

**Success Criteria** (what must be TRUE):
1. La commande process exécute le workflow complet: scan -> parsing -> matching -> validation -> transfert
2. La commande pending affiche la liste des fichiers en attente de validation
3. La commande validate permet de valider un fichier spécifique par son ID

Plans:
- [x] 07-01-PLAN.md — Commandes CLI process, pending, validate avec callback verbose/quiet et intégration validate_app

### Phase 8: Import et Maintenance

**Goal**: Importer une vidéothèque existante dans la BDD et fournir les outils de maintenance (symlinks, intégrité)
**Depends on**: Phase 3, Phase 4, Phase 5
**Requirements**: CLI-04, CLI-05, CLI-06, CLI-07, IMP-01, IMP-02, IMP-03, IMP-04
**Status**: COMPLETE (2026-01-28)

**Success Criteria** (what must be TRUE):
1. La commande import scanne la vidéothèque existante et importe les fichiers dans la BDD
2. L'enrichissement via API récupère les métadonnées avec rate limiting respecté
3. La commande repair-links détecte et répare les symlinks cassés
4. La commande check vérifie la cohérence entre BDD et fichiers réels
5. La commande enrich permet d'enrichir les métadonnées via API pour les fichiers existants

Plans:
- [x] 08-01-PLAN.md — ImporterService et commande import avec détection doublons par hash
- [x] 08-02-PLAN.md — EnricherService, IntegrityChecker, RepairService et commandes enrich, repair-links, check

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Fondations Architecture | 2/2 | Complete | 2026-01-26 |
| 2. Parsing et Scan | 2/2 | Complete | 2026-01-27 |
| 3. Clients API | 4/4 | Complete | 2026-01-27 |
| 4. Persistance | 2/2 | Complete | 2026-01-27 |
| 5. Organisation Fichiers | 2/2 | Complete | 2026-01-27 |
| 6. Validation | 2/2 | Complete | 2026-01-28 |
| 7. CLI Principale | 1/1 | Complete | 2026-01-28 |
| 8. Import et Maintenance | 2/2 | Complete | 2026-01-28 |

## Milestone Summary

**Key Decisions:**
- Architecture hexagonale choisie pour éviter le couplage CLI/métier de la v1
- CLI avant Web pour valider le cœur métier d'abord
- @dataclass(frozen=True) for value objects to guarantee immutability
- ABC with @abstractmethod for ports to enforce interface contracts
- Async methods for IMediaAPIClient to support httpx async client
- diskcache for persistence (file-based, no external server needed)
- xxhash pour hash rapide (échantillons début/fin/taille au lieu de fichier complet)
- token_sort_ratio with processor for case-insensitive word-order-independent matching
- THRESHOLD = 85 pour auto-validation (cohérent avec MatcherService.MATCH_THRESHOLD)

**Issues Resolved:**
- Séparation domain/infrastructure complète permettant réutilisation CLI/Web
- Rate limiting robuste avec tenacity pour éviter les erreurs 429
- Détection doublons par hash au lieu de path pour import fiable
- Symlinks relatifs pour portabilité entre systèmes

**Technical Debt Incurred:**
- None - All implementations complete without placeholders or TODOs

---

*Archived: 2026-01-28 as part of v1.0 milestone completion*
*For current project status, see .planning/ROADMAP.md*
