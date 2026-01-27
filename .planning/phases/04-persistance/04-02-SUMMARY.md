---
phase: 04-persistance
plan: 02
subsystem: persistence
tags: [sqlmodel, repositories, xxhash, di]
requires: ["04-01"]
provides: ["repositories", "hash-service", "di-integration"]
affects: ["05-matching"]
tech-stack:
  added: ["xxhash"]
  patterns: ["repository-pattern", "dependency-injection"]
key-files:
  created:
    - src/infrastructure/persistence/hash_service.py
    - src/infrastructure/persistence/repositories/__init__.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/infrastructure/persistence/repositories/series_repository.py
    - src/infrastructure/persistence/repositories/episode_repository.py
    - src/infrastructure/persistence/repositories/video_file_repository.py
    - src/infrastructure/persistence/repositories/pending_validation_repository.py
  modified:
    - src/infrastructure/persistence/__init__.py
    - src/container.py
    - requirements.txt
decisions:
  - xxhash pour hash rapide (echantillons debut/fin/taille)
  - Factory provider pour repositories (session fraiche par appel)
  - Conversion tuple <-> JSON pour genres/languages
metrics:
  duration: 3 min
  completed: 2026-01-27
---

# Phase 4 Plan 02: Repositories SQLModel et Hash Service Summary

**One-liner:** Repositories SQLModel implementant les ports avec hash XXHash par echantillons et integration DI

## What Was Built

### Hash Service (compute_file_hash)
- Algorithme XXHash (xxh3_64) par echantillons pour fichiers video
- Lit uniquement debut (1 Mo) + fin (1 Mo) + taille totale
- 10x plus rapide que MD5/SHA sur gros fichiers
- Hash deterministe de 16 caracteres hex

### Repositories SQLModel
- **SQLModelMovieRepository** : CRUD complet pour films, recherche par titre/TMDB ID
- **SQLModelSeriesRepository** : CRUD complet pour series, recherche par titre/TVDB ID
- **SQLModelEpisodeRepository** : Episodes avec filtrage series/saison/episode
- **SQLModelVideoFileRepository** : Fichiers video avec list_pending()
- **SQLModelPendingValidationRepository** : Validations en attente

### Integration DI
- `providers.Resource(init_db)` pour initialisation unique de la DB
- `providers.Factory` pour session fraiche a chaque appel repository
- 5 repositories injectes via le container

## Key Changes

| File | Change |
|------|--------|
| hash_service.py | Service XXHash avec echantillonnage |
| repositories/*.py | 5 implementations des ports ABC |
| container.py | 6 nouveaux providers (database, session, 5 repos) |
| requirements.txt | xxhash>=3.6.0 |

## Technical Decisions

1. **XXHash par echantillons** : Hash debut/fin/taille suffisant pour detection doublons video (headers uniques)
2. **Factory pour repositories** : Session fraiche evite les problemes d'expiration/detachement
3. **Conversion tuple/JSON** : genres et languages stockes en JSON, convertis en tuple pour entites

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 3f3063e | feat | Service de hash XXHash par echantillons |
| c24eda3 | feat | Repositories SQLModel implementant les ports |
| b7944c8 | feat | Integration repositories au container DI |

## Deviations from Plan

None - plan execute exactement comme ecrit.

## Verification Results

```
Hash service: OK (16 caracteres hex, deterministe)
MovieRepository: implemente IMovieRepository, genres tuple OK
SeriesRepository: implemente ISeriesRepository
EpisodeRepository: filtrage series/season/episode OK
VideoFileRepository: list_pending() OK
PendingValidationRepository: CRUD complet OK
Container DI: tous repositories injectes OK
```

## Next Phase Readiness

**Phase 5 (Matching) prerequisites met:**
- [x] Repositories disponibles via DI
- [x] Entites Video/Movie/Series/Episode persistables
- [x] Hash service pour deduplication
- [x] PendingValidation pour workflow validation

**Ready for:**
- MatchingService utilisant repositories + clients API
- Workflow scan -> parse -> match -> persist
