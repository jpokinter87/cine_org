# Requirements Archive: v1.0 MVP CLI Application

**Archived:** 2026-01-28
**Status:** SHIPPED

This is the archived requirements specification for v1.0.
For current requirements, see `.planning/REQUIREMENTS.md` (created for next milestone).

---

## v1 Requirements

### Architecture

- [x] **ARCH-01**: Structure hexagonale avec séparation domain/application/infrastructure/adapters
- [x] **ARCH-02**: Container d'injection de dépendances partagé entre CLI et Web
- [x] **ARCH-03**: Configuration via pydantic-settings avec validation
- [x] **ARCH-04**: Logging structuré avec rotation et niveaux configurables

### Parsing

- [x] **PARS-01**: Scan récursif des répertoires téléchargements/Films et téléchargements/Séries
- [x] **PARS-02**: Extraction métadonnées via guessit (titre, année, saison, épisode)
- [x] **PARS-03**: Extraction infos techniques via mediainfo (codec, résolution, langues, durée)
- [x] **PARS-04**: Détection automatique du type (film vs série) avec correction si mal placé

### APIs

- [x] **API-01**: Client TMDB pour recherche et récupération métadonnées films
- [x] **API-02**: Client TVDB pour recherche et récupération métadonnées séries/épisodes
- [x] **API-03**: Système de scoring (titre 50% + année 25% + durée 25%) avec seuil 85%
- [x] **API-04**: Cache des résultats API (24h recherches, 7j détails)
- [x] **API-05**: Rate limiting avec retry automatique et backoff exponentiel

### Validation

- [x] **VALID-01**: Validation automatique si score >= 85% et résultat unique
- [x] **VALID-02**: Interface CLI pour validation manuelle (affichage candidats, sélection)
- [x] **VALID-03**: Recherche manuelle par titre libre et saisie ID IMDB/TMDB/TVDB
- [x] **VALID-04**: Validation finale batch avant transfert (liste tous les fichiers, destinations)

### Organisation

- [x] **ORG-01**: Renommage selon format standardisé (Titre (Année) Langue Codec Résolution)
- [x] **ORG-02**: Organisation films par genre puis lettre alphabétique
- [x] **ORG-03**: Organisation séries par lettre alphabétique avec dossiers Saison XX
- [x] **ORG-04**: Création symlinks dans répertoire video/ pointant vers stockage/

### Persistance

- [x] **DB-01**: Base SQLite avec SQLModel (tables films, séries, épisodes)
- [x] **DB-02**: Table pending_validation pour fichiers en attente
- [x] **DB-03**: Table trash pour historique des suppressions
- [x] **DB-04**: Index sur colonnes fréquemment utilisées (tmdb_id, tvdb_id, title)
- [x] **DB-05**: Calcul et stockage hash de fichier pour détection de doublons

### Import

- [x] **IMP-01**: Scan vidéothèque existante et import dans BDD
- [x] **IMP-02**: Enrichissement métadonnées via API avec rate limiting
- [x] **IMP-03**: Détection et réparation symlinks cassés
- [x] **IMP-04**: Vérification intégrité (cohérence BDD vs fichiers réels)

### CLI

- [x] **CLI-01**: Commande process (scan -> parsing -> matching -> validation -> transfert)
- [x] **CLI-02**: Commande pending (afficher fichiers en attente de validation)
- [x] **CLI-03**: Commande validate (valider un fichier spécifique)
- [x] **CLI-04**: Commande import (importer vidéothèque existante)
- [x] **CLI-05**: Commande enrich (enrichir métadonnées via API)
- [x] **CLI-06**: Commande repair-links (analyser et réparer symlinks)
- [x] **CLI-07**: Commande check (vérifier intégrité vidéothèque)

## Traceability

| Requirement | Phase | Status | Outcome |
|-------------|-------|--------|---------|
| ARCH-01 | Phase 1 | Complete | Validated - structure propre |
| ARCH-02 | Phase 1 | Complete | Validated - DI fonctionne |
| ARCH-03 | Phase 1 | Complete | Validated - config flexible |
| ARCH-04 | Phase 1 | Complete | Validated - logs JSON + console |
| PARS-01 | Phase 2 | Complete | Validated - scan récursif |
| PARS-02 | Phase 2 | Complete | Validated - guessit intégré |
| PARS-03 | Phase 2 | Complete | Validated - mediainfo intégré |
| PARS-04 | Phase 2 | Complete | Validated - détection type |
| API-01 | Phase 3 | Complete | Validated - TMDB client |
| API-02 | Phase 3 | Complete | Validated - TVDB client |
| API-03 | Phase 3 | Complete | Validated - scoring 50/25/25 |
| API-04 | Phase 3 | Complete | Validated - cache diskcache |
| API-05 | Phase 3 | Complete | Validated - tenacity retry |
| DB-01 | Phase 4 | Complete | Validated - SQLModel tables |
| DB-02 | Phase 4 | Complete | Validated - pending_validation |
| DB-03 | Phase 4 | Complete | Validated - trash table |
| DB-04 | Phase 4 | Complete | Validated - index créés |
| DB-05 | Phase 4 | Complete | Validated - xxhash |
| ORG-01 | Phase 5 | Complete | Validated - renommage |
| ORG-02 | Phase 5 | Complete | Validated - films/genre/lettre |
| ORG-03 | Phase 5 | Complete | Validated - séries/lettre/saison |
| ORG-04 | Phase 5 | Complete | Validated - symlinks relatifs |
| VALID-01 | Phase 6 | Complete | Validated - auto >= 85% |
| VALID-02 | Phase 6 | Complete | Validated - Rich interface |
| VALID-03 | Phase 6 | Complete | Validated - recherche manuelle |
| VALID-04 | Phase 6 | Complete | Validated - batch preview |
| CLI-01 | Phase 7 | Complete | Validated - process workflow |
| CLI-02 | Phase 7 | Complete | Validated - pending list |
| CLI-03 | Phase 7 | Complete | Validated - validate command |
| CLI-04 | Phase 8 | Complete | Validated - import command |
| CLI-05 | Phase 8 | Complete | Validated - enrich command |
| CLI-06 | Phase 8 | Complete | Validated - repair-links |
| CLI-07 | Phase 8 | Complete | Validated - check command |
| IMP-01 | Phase 8 | Complete | Validated - ImporterService |
| IMP-02 | Phase 8 | Complete | Validated - EnricherService |
| IMP-03 | Phase 8 | Complete | Validated - RepairService |
| IMP-04 | Phase 8 | Complete | Validated - IntegrityChecker |

## Milestone Summary

**Shipped:** 32 of 32 v1 requirements (100%)

**Adjusted:** None - all requirements implemented as specified

**Dropped:** None

**Coverage:**
- v1 requirements: 32 total
- Mapped to phases: 32
- Validated: 32

---

*Archived: 2026-01-28 as part of v1.0 milestone completion*
