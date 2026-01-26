# Roadmap: CineOrg

## Overview

CineOrg est une reecriture complete d'une application de gestion de videotheque. Le parcours demarre par les fondations architecturales (hexagonale) pour eviter le couplage CLI/metier de la v1, puis etablit l'infrastructure (parsing, APIs, base de donnees), implemente les services metier avec injection de dependances, construit progressivement la CLI avec les commandes de traitement et validation, et termine par l'import de la videotheque existante avec les outils de maintenance.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Fondations Architecture** - Structure hexagonale, DI container, configuration
- [ ] **Phase 2: Parsing et Scan** - Scan repertoires, extraction metadonnees via guessit/mediainfo
- [ ] **Phase 3: Clients API** - Clients TMDB/TVDB avec rate limiting, cache, scoring
- [ ] **Phase 4: Persistance** - Base SQLite avec SQLModel, tables metier
- [ ] **Phase 5: Organisation Fichiers** - Renommage, structure repertoires, symlinks
- [ ] **Phase 6: Validation** - Matching automatique et validation manuelle CLI
- [ ] **Phase 7: CLI Principale** - Commandes process, pending, validate
- [ ] **Phase 8: Import et Maintenance** - Import videotheque existante, reparation, verification

## Phase Details

### Phase 1: Fondations Architecture
**Goal**: Etablir l'architecture hexagonale avec separation stricte domain/application/infrastructure pour garantir la reutilisabilite entre CLI et Web
**Depends on**: Nothing (first phase)
**Requirements**: ARCH-01, ARCH-02, ARCH-03, ARCH-04
**Success Criteria** (what must be TRUE):
  1. La structure de repertoires domain/application/infrastructure/adapters existe avec __init__.py
  2. Le container DI peut injecter des implementations concretes pour les ports abstraits
  3. La configuration via pydantic-settings charge les variables d'environnement et fichier config
  4. Le logging structure ecrit des logs JSON avec rotation et niveaux configurables
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Structure hexagonale, entites domain et ports abstraits
- [x] 01-02-PLAN.md — Container DI, configuration pydantic-settings et logging loguru

### Phase 2: Parsing et Scan
**Goal**: Scanner les repertoires de telechargements et extraire les metadonnees des fichiers video via guessit et mediainfo
**Depends on**: Phase 1
**Requirements**: PARS-01, PARS-02, PARS-03, PARS-04
**Success Criteria** (what must be TRUE):
  1. Le scan recursif detecte tous les fichiers video dans telechargements/Films et telechargements/Series
  2. Guessit extrait correctement titre, annee, saison, episode des noms de fichiers
  3. Mediainfo extrait codec, resolution, langues audio, duree des fichiers
  4. Le type (film vs serie) est detecte automatiquement et corrige si le fichier est mal place
**Plans**: TBD

Plans:
- [ ] 02-01: Scanner de fichiers async
- [ ] 02-02: Parsers guessit et mediainfo

### Phase 3: Clients API
**Goal**: Interroger TMDB et TVDB pour rechercher et recuperer les metadonnees films/series avec gestion robuste du rate limiting
**Depends on**: Phase 1
**Requirements**: API-01, API-02, API-03, API-04, API-05
**Success Criteria** (what must be TRUE):
  1. Le client TMDB recherche des films par titre et recupere les metadonnees completes
  2. Le client TVDB recherche des series/episodes et recupere les metadonnees completes
  3. Le scoring (titre 50% + annee 25% + duree 25%) classe les candidats avec seuil 85%
  4. Les resultats API sont caches (24h recherches, 7j details)
  5. Le rate limiting avec retry et backoff exponentiel evite les erreurs 429
**Plans**: TBD

Plans:
- [ ] 03-01: Client TMDB avec rate limiting
- [ ] 03-02: Client TVDB avec rate limiting
- [ ] 03-03: Systeme de scoring et cache

### Phase 4: Persistance
**Goal**: Stocker films, series, episodes et fichiers en attente dans une base SQLite avec SQLModel
**Depends on**: Phase 1
**Requirements**: DB-01, DB-02, DB-03, DB-04, DB-05
**Success Criteria** (what must be TRUE):
  1. Les tables films, series, episodes existent avec leurs relations
  2. La table pending_validation stocke les fichiers en attente de validation manuelle
  3. La table trash conserve l'historique des suppressions
  4. Les index sur tmdb_id, tvdb_id, title accelerent les recherches
  5. Le hash de fichier est calcule et stocke pour detecter les doublons
**Plans**: TBD

Plans:
- [ ] 04-01: Modeles SQLModel et migrations
- [ ] 04-02: Repositories et hash de fichiers

### Phase 5: Organisation Fichiers
**Goal**: Renommer les fichiers selon le format standardise et les organiser dans la structure videotheque avec symlinks
**Depends on**: Phase 4
**Requirements**: ORG-01, ORG-02, ORG-03, ORG-04
**Success Criteria** (what must be TRUE):
  1. Les fichiers sont renommes au format "Titre (Annee) Langue Codec Resolution.ext"
  2. Les films sont organises dans stockage/Films/Genre/Lettre/
  3. Les series sont organisees dans stockage/Series/Lettre/Titre/Saison XX/
  4. Les symlinks dans video/ pointent vers les fichiers dans stockage/
**Plans**: TBD

Plans:
- [ ] 05-01: Renommage et transfert fichiers
- [ ] 05-02: Structure repertoires et symlinks

### Phase 6: Validation
**Goal**: Valider automatiquement les correspondances avec score >= 85% et permettre la validation manuelle pour les cas ambigus via CLI
**Depends on**: Phase 3, Phase 4
**Requirements**: VALID-01, VALID-02, VALID-03, VALID-04
**Success Criteria** (what must be TRUE):
  1. Les fichiers avec score >= 85% et resultat unique sont valides automatiquement
  2. L'utilisateur peut voir les candidats et selectionner le bon match via CLI
  3. L'utilisateur peut rechercher manuellement par titre ou saisir un ID IMDB/TMDB/TVDB
  4. La validation finale batch affiche tous les fichiers avec leurs destinations avant transfert
**Plans**: TBD

Plans:
- [ ] 06-01: Validation automatique et workflow
- [ ] 06-02: Interface CLI validation manuelle

### Phase 7: CLI Principale
**Goal**: Fournir les commandes CLI pour le workflow principal: scan, traitement, et gestion des fichiers en attente
**Depends on**: Phase 2, Phase 5, Phase 6
**Requirements**: CLI-01, CLI-02, CLI-03
**Success Criteria** (what must be TRUE):
  1. La commande process execute le workflow complet: scan -> parsing -> matching -> validation -> transfert
  2. La commande pending affiche la liste des fichiers en attente de validation
  3. La commande validate permet de valider un fichier specifique par son ID
**Plans**: TBD

Plans:
- [ ] 07-01: Commandes process, pending, validate

### Phase 8: Import et Maintenance
**Goal**: Importer une videotheque existante dans la BDD et fournir les outils de maintenance (symlinks, integrite)
**Depends on**: Phase 3, Phase 4, Phase 5
**Requirements**: CLI-04, CLI-05, CLI-06, CLI-07, IMP-01, IMP-02, IMP-03, IMP-04
**Success Criteria** (what must be TRUE):
  1. La commande import scanne la videotheque existante et importe les fichiers dans la BDD
  2. L'enrichissement via API recupere les metadonnees avec rate limiting respecte
  3. La commande repair-links detecte et repare les symlinks casses
  4. La commande check verifie la coherence entre BDD et fichiers reels
  5. La commande enrich permet d'enrichir les metadonnees via API pour les fichiers existants
**Plans**: TBD

Plans:
- [ ] 08-01: Import videotheque existante
- [ ] 08-02: Commandes maintenance (enrich, repair-links, check)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Fondations Architecture | 2/2 | Complete | 2026-01-26 |
| 2. Parsing et Scan | 0/2 | Not started | - |
| 3. Clients API | 0/3 | Not started | - |
| 4. Persistance | 0/2 | Not started | - |
| 5. Organisation Fichiers | 0/2 | Not started | - |
| 6. Validation | 0/2 | Not started | - |
| 7. CLI Principale | 0/1 | Not started | - |
| 8. Import et Maintenance | 0/2 | Not started | - |

---
*Roadmap created: 2026-01-26*
*Phase 1 planned: 2026-01-26*
*Total: 8 phases, 16 plans, 32 requirements*
