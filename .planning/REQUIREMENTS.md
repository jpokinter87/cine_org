# Requirements: CineOrg

**Defined:** 2025-01-26
**Core Value:** Architecture propre avec séparation claire entre logique métier et interfaces

## v1 Requirements

### Architecture

- [ ] **ARCH-01**: Structure hexagonale avec séparation domain/application/infrastructure/adapters
- [ ] **ARCH-02**: Container d'injection de dépendances partagé entre CLI et Web
- [ ] **ARCH-03**: Configuration via pydantic-settings avec validation
- [ ] **ARCH-04**: Logging structuré avec rotation et niveaux configurables

### Parsing

- [ ] **PARS-01**: Scan récursif des répertoires téléchargements/Films et téléchargements/Séries
- [ ] **PARS-02**: Extraction métadonnées via guessit (titre, année, saison, épisode)
- [ ] **PARS-03**: Extraction infos techniques via mediainfo (codec, résolution, langues, durée)
- [ ] **PARS-04**: Détection automatique du type (film vs série) avec correction si mal placé

### APIs

- [ ] **API-01**: Client TMDB pour recherche et récupération métadonnées films
- [ ] **API-02**: Client TVDB pour recherche et récupération métadonnées séries/épisodes
- [ ] **API-03**: Système de scoring (titre 50% + année 25% + durée 25%) avec seuil 85%
- [ ] **API-04**: Cache des résultats API (24h recherches, 7j détails)
- [ ] **API-05**: Rate limiting avec retry automatique et backoff exponentiel

### Validation

- [ ] **VALID-01**: Validation automatique si score ≥ 85% et résultat unique
- [ ] **VALID-02**: Interface CLI pour validation manuelle (affichage candidats, sélection)
- [ ] **VALID-03**: Recherche manuelle par titre libre et saisie ID IMDB/TMDB/TVDB
- [ ] **VALID-04**: Validation finale batch avant transfert (liste tous les fichiers, destinations)

### Organisation

- [ ] **ORG-01**: Renommage selon format standardisé (Titre (Année) Langue Codec Résolution)
- [ ] **ORG-02**: Organisation films par genre puis lettre alphabétique
- [ ] **ORG-03**: Organisation séries par lettre alphabétique avec dossiers Saison XX
- [ ] **ORG-04**: Création symlinks dans répertoire vidéo/ pointant vers stockage/

### Persistance

- [ ] **DB-01**: Base SQLite avec SQLModel (tables films, series, episodes)
- [ ] **DB-02**: Table pending_validation pour fichiers en attente
- [ ] **DB-03**: Table trash pour historique des suppressions
- [ ] **DB-04**: Index sur colonnes fréquemment utilisées (tmdb_id, tvdb_id, title)
- [ ] **DB-05**: Calcul et stockage hash de fichier pour détection de doublons

### Import

- [ ] **IMP-01**: Scan vidéothèque existante et import dans BDD
- [ ] **IMP-02**: Enrichissement métadonnées via API avec rate limiting
- [ ] **IMP-03**: Détection et réparation symlinks cassés
- [ ] **IMP-04**: Vérification intégrité (cohérence BDD vs fichiers réels)

### CLI

- [ ] **CLI-01**: Commande process (scan → parsing → matching → validation → transfert)
- [ ] **CLI-02**: Commande pending (afficher fichiers en attente de validation)
- [ ] **CLI-03**: Commande validate (valider un fichier spécifique)
- [ ] **CLI-04**: Commande import (importer vidéothèque existante)
- [ ] **CLI-05**: Commande enrich (enrichir métadonnées via API)
- [ ] **CLI-06**: Commande repair-links (analyser et réparer symlinks)
- [ ] **CLI-07**: Commande check (vérifier intégrité vidéothèque)

## v2 Requirements

### Interface Web

- **WEB-01**: Serveur FastAPI avec commande serve
- **WEB-02**: Dashboard avec statistiques vidéothèque
- **WEB-03**: Interface de validation manuelle avec posters et bandes-annonces
- **WEB-04**: Page de validation finale avant transfert

### Features Avancées

- **ADV-01**: Détection doublons avant transfert
- **ADV-02**: Subdivision dynamique des répertoires (>50 fichiers)
- **ADV-03**: Mode dry-run / preview pour simulation
- **ADV-04**: Commande stats (statistiques de la vidéothèque)
- **ADV-05**: Commande reorganize (réorganisation et subdivision)
- **ADV-06**: Collections et sagas (regroupement franchises)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Intégration AniDB/MAL | Évolution future, architecture prête mais pas implémenté |
| Recherche/filtrage dans l'interface | Mentionné comme non prévu dans les specs |
| Génération poster.jpg/fanart.jpg | Explicitement exclu des specs |
| Multi-utilisateurs | Usage personnel uniquement |
| Streaming intégré | Délégué à Plex/Jellyfin |
| Daemon/watchdog | Exécution manuelle uniquement |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ARCH-01 | Phase 1 | Pending |
| ARCH-02 | Phase 1 | Pending |
| ARCH-03 | Phase 1 | Pending |
| ARCH-04 | Phase 1 | Pending |
| PARS-01 | Phase 2 | Pending |
| PARS-02 | Phase 2 | Pending |
| PARS-03 | Phase 2 | Pending |
| PARS-04 | Phase 2 | Pending |
| API-01 | Phase 3 | Pending |
| API-02 | Phase 3 | Pending |
| API-03 | Phase 3 | Pending |
| API-04 | Phase 3 | Pending |
| API-05 | Phase 3 | Pending |
| DB-01 | Phase 4 | Pending |
| DB-02 | Phase 4 | Pending |
| DB-03 | Phase 4 | Pending |
| DB-04 | Phase 4 | Pending |
| DB-05 | Phase 4 | Pending |
| ORG-01 | Phase 5 | Pending |
| ORG-02 | Phase 5 | Pending |
| ORG-03 | Phase 5 | Pending |
| ORG-04 | Phase 5 | Pending |
| VALID-01 | Phase 6 | Pending |
| VALID-02 | Phase 6 | Pending |
| VALID-03 | Phase 6 | Pending |
| VALID-04 | Phase 6 | Pending |
| CLI-01 | Phase 7 | Pending |
| CLI-02 | Phase 7 | Pending |
| CLI-03 | Phase 7 | Pending |
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
- Unmapped: 0 ✓

---
*Requirements defined: 2025-01-26*
*Last updated: 2025-01-26 after initial definition*
