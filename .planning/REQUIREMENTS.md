# Requirements: CineOrg

**Defined:** 2025-01-26
**Core Value:** Architecture propre avec separation claire entre logique metier et interfaces

## v1 Requirements

### Architecture

- [x] **ARCH-01**: Structure hexagonale avec separation domain/application/infrastructure/adapters
- [x] **ARCH-02**: Container d'injection de dependances partage entre CLI et Web
- [x] **ARCH-03**: Configuration via pydantic-settings avec validation
- [x] **ARCH-04**: Logging structure avec rotation et niveaux configurables

### Parsing

- [x] **PARS-01**: Scan recursif des repertoires telechargements/Films et telechargements/Series
- [x] **PARS-02**: Extraction metadonnees via guessit (titre, annee, saison, episode)
- [x] **PARS-03**: Extraction infos techniques via mediainfo (codec, resolution, langues, duree)
- [x] **PARS-04**: Detection automatique du type (film vs serie) avec correction si mal place

### APIs

- [x] **API-01**: Client TMDB pour recherche et recuperation metadonnees films
- [x] **API-02**: Client TVDB pour recherche et recuperation metadonnees series/episodes
- [x] **API-03**: Systeme de scoring (titre 50% + annee 25% + duree 25%) avec seuil 85%
- [x] **API-04**: Cache des resultats API (24h recherches, 7j details)
- [x] **API-05**: Rate limiting avec retry automatique et backoff exponentiel

### Validation

- [x] **VALID-01**: Validation automatique si score >= 85% et resultat unique
- [x] **VALID-02**: Interface CLI pour validation manuelle (affichage candidats, selection)
- [x] **VALID-03**: Recherche manuelle par titre libre et saisie ID IMDB/TMDB/TVDB
- [x] **VALID-04**: Validation finale batch avant transfert (liste tous les fichiers, destinations)

### Organisation

- [x] **ORG-01**: Renommage selon format standardise (Titre (Annee) Langue Codec Resolution)
- [x] **ORG-02**: Organisation films par genre puis lettre alphabetique
- [x] **ORG-03**: Organisation series par lettre alphabetique avec dossiers Saison XX
- [x] **ORG-04**: Creation symlinks dans repertoire video/ pointant vers stockage/

### Persistance

- [x] **DB-01**: Base SQLite avec SQLModel (tables films, series, episodes)
- [x] **DB-02**: Table pending_validation pour fichiers en attente
- [x] **DB-03**: Table trash pour historique des suppressions
- [x] **DB-04**: Index sur colonnes frequemment utilisees (tmdb_id, tvdb_id, title)
- [x] **DB-05**: Calcul et stockage hash de fichier pour detection de doublons

### Import

- [ ] **IMP-01**: Scan videotheque existante et import dans BDD
- [ ] **IMP-02**: Enrichissement metadonnees via API avec rate limiting
- [ ] **IMP-03**: Detection et reparation symlinks casses
- [ ] **IMP-04**: Verification integrite (coherence BDD vs fichiers reels)

### CLI

- [x] **CLI-01**: Commande process (scan -> parsing -> matching -> validation -> transfert)
- [x] **CLI-02**: Commande pending (afficher fichiers en attente de validation)
- [x] **CLI-03**: Commande validate (valider un fichier specifique)
- [ ] **CLI-04**: Commande import (importer videotheque existante)
- [ ] **CLI-05**: Commande enrich (enrichir metadonnees via API)
- [ ] **CLI-06**: Commande repair-links (analyser et reparer symlinks)
- [ ] **CLI-07**: Commande check (verifier integrite videotheque)

## v2 Requirements

### Interface Web

- **WEB-01**: Serveur FastAPI avec commande serve
- **WEB-02**: Dashboard avec statistiques videotheque
- **WEB-03**: Interface de validation manuelle avec posters et bandes-annonces
- **WEB-04**: Page de validation finale avant transfert

### Features Avancees

- **ADV-01**: Detection doublons avant transfert
- **ADV-02**: Subdivision dynamique des repertoires (>50 fichiers)
- **ADV-03**: Mode dry-run / preview pour simulation
- **ADV-04**: Commande stats (statistiques de la videotheque)
- **ADV-05**: Commande reorganize (reorganisation et subdivision)
- **ADV-06**: Collections et sagas (regroupement franchises)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Integration AniDB/MAL | Evolution future, architecture prete mais pas implemente |
| Recherche/filtrage dans l'interface | Mentionne comme non prevu dans les specs |
| Generation poster.jpg/fanart.jpg | Explicitement exclu des specs |
| Multi-utilisateurs | Usage personnel uniquement |
| Streaming integre | Delegue a Plex/Jellyfin |
| Daemon/watchdog | Execution manuelle uniquement |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ARCH-01 | Phase 1 | Complete |
| ARCH-02 | Phase 1 | Complete |
| ARCH-03 | Phase 1 | Complete |
| ARCH-04 | Phase 1 | Complete |
| PARS-01 | Phase 2 | Complete |
| PARS-02 | Phase 2 | Complete |
| PARS-03 | Phase 2 | Complete |
| PARS-04 | Phase 2 | Complete |
| API-01 | Phase 3 | Complete |
| API-02 | Phase 3 | Complete |
| API-03 | Phase 3 | Complete |
| API-04 | Phase 3 | Complete |
| API-05 | Phase 3 | Complete |
| DB-01 | Phase 4 | Complete |
| DB-02 | Phase 4 | Complete |
| DB-03 | Phase 4 | Complete |
| DB-04 | Phase 4 | Complete |
| DB-05 | Phase 4 | Complete |
| ORG-01 | Phase 5 | Complete |
| ORG-02 | Phase 5 | Complete |
| ORG-03 | Phase 5 | Complete |
| ORG-04 | Phase 5 | Complete |
| VALID-01 | Phase 6 | Complete |
| VALID-02 | Phase 6 | Complete |
| VALID-03 | Phase 6 | Complete |
| VALID-04 | Phase 6 | Complete |
| CLI-01 | Phase 7 | Complete |
| CLI-02 | Phase 7 | Complete |
| CLI-03 | Phase 7 | Complete |
| CLI-04 | Phase 8 | Pending |
| CLI-05 | Phase 8 | Pending |
| CLI-06 | Phase 8 | Pending |
| CLI-07 | Phase 8 | Pending |
| IMP-01 | Phase 8 | Pending |
| IMP-02 | Phase 8 | Pending |
| IMP-03 | Phase 8 | Pending |
| IMP-04 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0

---
*Requirements defined: 2025-01-26*
*Last updated: 2026-01-28 after Phase 7 completion*
