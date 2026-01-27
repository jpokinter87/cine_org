---
phase: 05-organisation-fichiers
plan: 01
subsystem: services
tags: [renamer, organizer, quality-scorer, tdd, pure-functions]

dependency-graph:
  requires: [01-01, 01-02, 02-01]
  provides: [RenamerService, OrganizerService, QualityScorerService]
  affects: [05-02, 08-01]

tech-stack:
  added: [pathvalidate]
  patterns: [pure-functions, dataclass-frozen, strategy-scoring]

key-files:
  created:
    - src/services/renamer.py
    - src/services/organizer.py
    - src/services/quality_scorer.py
    - tests/unit/services/test_renamer.py
    - tests/unit/services/test_organizer.py
    - tests/unit/services/test_quality_scorer.py
  modified:
    - requirements.txt

decisions:
  - id: ellipsis-placeholder
    choice: "Utiliser caractere Unicode ellipse comme placeholder pour preserver les ... en fin de chaine"
    reason: "pathvalidate supprime les points finaux (regle Windows)"
  - id: priority-genre-hierarchy
    choice: "Retourner le premier genre de la hierarchie trouve dans les genres du film"
    reason: "Garantit un classement coherent independamment de l'ordre des genres fournis par l'API"
  - id: multi-audio-best-score
    choice: "Pour multi-pistes audio, prendre le meilleur score"
    reason: "La meilleure piste represente la qualite maximale disponible"

metrics:
  duration: 7 min
  completed: 2026-01-27
---

# Phase 5 Plan 1: Services Organisation Fichiers Summary

**One-liner:** Services purs de renommage (ligatures/sanitization), organisation (articles/genres) et scoring qualite multi-criteres.

## What Was Built

### RenamerService (src/services/renamer.py)
- `sanitize_for_filesystem()`: Nettoyage noms fichiers
  - Ligatures francaises: oe -> oe, ae -> ae
  - Caracteres speciaux: : / \ * " < > | -> tiret
  - Point d'interrogation: ? -> ... (avec placeholder Unicode)
  - Troncature a 200 caracteres
- `format_language_code()`: FR/EN pour mono, MULTi pour plusieurs
- `generate_movie_filename()`: Titre (Annee) Langue Codec Resolution.ext
- `generate_series_filename()`: Titre (Annee) - SxxExx - Episode - tech.ext

### OrganizerService (src/services/organizer.py)
- `get_sort_letter()`: Extraction lettre de tri
  - Ignore articles fr/en/de/es (Le, La, The, Der, El...)
  - Gere l'apostrophe (L'Odyssee -> O)
  - Titres numeriques et speciaux -> #
- `get_priority_genre()`: Selection selon GENRE_HIERARCHY
  - Animation > Science-Fiction > Fantastique > ... > Divers
- `get_movie_destination()`: stockage/Films/Genre/Lettre
- `get_series_destination()`: stockage/Series/Lettre/Titre (Annee)/Saison XX
- `SubdivisionRange`: Dataclass pour subdivision future (Phase 8)

### QualityScorerService (src/services/quality_scorer.py)
- `score_resolution()`: 4K(100) > 1080p(75) > 720p(50) > SD(25)
- `score_video_codec()`: AV1(100) > HEVC(85) > VP9(70) > H.264(60) > anciens(30)
- `score_audio()`: codec(70%) + canaux(30%), meilleure piste en multi
- `calculate_quality_score()`: Score pondere total
  - Resolution: 30%
  - Codec video: 25%
  - Bitrate: 20%
  - Audio: 15%
  - Efficacite taille: 10%
- `QualityScore`: Dataclass avec breakdown property

## Test Coverage

| Service | Tests | Coverage |
|---------|-------|----------|
| renamer.py | 38 | 96% |
| organizer.py | 47 | 89% |
| quality_scorer.py | 39 | 92% |
| **Total** | **124** | **92%** |

## Key Implementation Details

### Ellipsis Placeholder (Rule 1 - Bug fix)
- **Probleme:** pathvalidate supprime les points en fin de chaine (regle Windows)
- **Solution:** Remplacer ? par U+2026 (ellipse Unicode), laisser pathvalidate nettoyer, puis restaurer en ...

### Scoring Multi-criteres
Les poids (30/25/20/15/10) ont ete choisis pour:
- Prioriser la resolution (impact visuel majeur)
- Valoriser les codecs modernes (HEVC/AV1)
- Inclure le bitrate comme indicateur de qualite
- L'audio compte moins (souvent upgrade facile)
- La taille comme bonus efficacite

## Dependencies

```
requirements.txt:
+ pathvalidate>=3.2.0  # Sanitization noms fichiers
```

## Architecture Links

```
renamer.py
  -> imports Movie, Series, Episode from core/entities/media.py
  -> imports MediaInfo from core/value_objects/media_info.py

organizer.py
  -> imports IGNORED_ARTICLES, GENRE_HIERARCHY from utils/constants.py
  -> imports Movie, Series from core/entities/media.py

quality_scorer.py
  -> imports MediaInfo, Resolution, VideoCodec, AudioCodec from core/value_objects/media_info.py
```

## Deviations from Plan

**None - plan executed exactly as written.**

## Next Phase Readiness

- [ ] RenamerService pret pour TransfererService (Plan 05-02)
- [ ] OrganizerService pret pour TransfererService (Plan 05-02)
- [ ] QualityScorerService pret pour gestion doublons (Plan 05-02)
- [ ] SubdivisionRange pret pour subdivision dynamique (Phase 8)
