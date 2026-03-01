---
phase: 29-films-multi-parties
plan: 01
subsystem: renamer, parser
tags: [guessit, renamer, multi-part, batch-builder, safety-net]

requires:
  - phase: 27-performance-robustesse-matching
    provides: VOSTFR subtitle_language in renamer
provides:
  - Extraction part depuis guessit (Part/Partie/Vol/Volume + chiffres arabes et romains)
  - Filet de securite doublons en fin de batch (detection + correction automatique)
  - Parametre part dans generate_movie/series_filename
affects: [30-normalisation-repertoires-series, 32-detection-doublons]

tech-stack:
  added: []
  patterns: [safety-net post-batch duplicate detection]

key-files:
  created:
    - tests/unit/adapters/cli/test_fix_duplicate_filenames.py
  modified:
    - src/core/value_objects/parsed_info.py
    - src/adapters/parsing/guessit_parser.py
    - src/services/renamer.py
    - src/adapters/cli/helpers.py
    - src/adapters/cli/batch_builder.py
    - tests/unit/test_guessit_parser.py
    - tests/unit/services/test_renamer.py

key-decisions:
  - "Filet de securite post-batch au lieu d'extraction en amont : plus simple et plus robuste"
  - "Parser extrait part systematiquement, filet ne l'utilise que si doublons detectes"
  - "Numerotation sequentielle si les noms originaux n'ont pas d'indication de part"

patterns-established:
  - "Safety-net pattern : detecter les anomalies post-generation et corriger automatiquement"

duration: ~45min
completed: 2026-03-01
---

# Phase 29 Plan 01: Films Multi-Parties Summary

**Filet de securite doublons pour films decoupes par le rippeur : detection post-batch + correction automatique avec suffixe "Partie N"**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-01 |
| Tasks | 3 completed |
| Files modified | 7 (+1 created) |
| Tests added | 18 (8 parser + 5 renamer + 5 filet) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Extraction part guessit natif (anglais) | Pass | `Best.Of.Youth.Part.2` → part=2 |
| AC-2: Extraction part titre (francais "Partie N") | Pass | `Nos.Meilleures.Annees.Partie.1` → part=1, titre nettoye |
| AC-3: Extraction part titre (francais autre film) | Pass | `Carlos.Partie.3` → part=3, titre nettoye |
| AC-4: Renamer inclut la partie dans le nom | Pass | `Nos meilleures annees (2003) Partie 2 Multi.mkv` |
| AC-5: Pas de partie = comportement inchange | Pass | `Inception (2010) Multi.mkv` (pas de "Partie") |
| AC-6: Batch builder propage la partie (decoupe rippeur) | Pass | Via filet de securite post-batch |
| AC-7: Pas de doublon pour vrais multi-parties TMDB | Pass | Kill Bill Vol 1/2 → titres TMDB differents, pas de doublon |

## Accomplishments

- Extraction robuste du numero de partie (Part/Partie/Vol/Volume, chiffres arabes et romains) dans le parser guessit
- Filet de securite post-batch : detecte les destinations identiques et corrige en ajoutant "Partie N"
- Fallback intelligent : numerotation sequentielle si les noms originaux n'ont pas d'indication de part
- 932 tests passent sans regression

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/core/value_objects/parsed_info.py` | Modified | Ajout champ `part: Optional[int]` a ParsedFilename |
| `src/adapters/parsing/guessit_parser.py` | Modified | Methodes `_extract_part`, `_roman_to_int` + import re |
| `src/services/renamer.py` | Modified | `title_has_part_indicator()`, param `part` aux generateurs |
| `src/adapters/cli/helpers.py` | Modified | Helpers `_extract_part_from_filename`, `_extract_subtitle_language_from_filename` |
| `src/adapters/cli/batch_builder.py` | Modified | `_fix_duplicate_filenames()` filet de securite post-batch |
| `tests/unit/test_guessit_parser.py` | Modified | 8 tests classe TestGuessitFilenameParserPart |
| `tests/unit/services/test_renamer.py` | Modified | 5 tests classe TestMultiPartFilename |
| `tests/unit/adapters/cli/test_fix_duplicate_filenames.py` | Created | 5 tests filet de securite doublons |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Filet post-batch au lieu d'extraction en amont | Plus simple et robuste : un seul point de correction | Le batch builder reste inchange, le filet intervient en fin de pipeline |
| Parser extrait `part` systematiquement | Necessaire pour le filet ; pas de condition sur le type TMDB | Champ `part` disponible pour d'autres usages futurs |
| `title_has_part_indicator()` conservee mais non utilisee en amont | Peut servir a la phase 32 (detection doublons) | Fonction utilitaire disponible |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Simplification architecturale | 1 | Positif — moins de complexite |

**Total impact:** Simplification majeure, meme resultat avec moins de code dans les call sites

### Detail

**1. Filet de securite au lieu d'extraction en amont**
- **Plan initial:** Extraire `part` dans chaque call site du batch builder (3 sites), verifier TMDB title, passer au renamer
- **Approche finale:** Le batch builder genere les noms normalement ; un filet en fin de pipeline detecte et corrige les doublons
- **Raison:** Suggestion de l'utilisateur — plus simple, plus robuste, couvre les cas imprevus
- **Impact:** 3 call sites restent inchanges, toute la logique est centralisee dans `_fix_duplicate_filenames`

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- Phase 29 complete, code stable
- 932 tests passent
- Pret pour phase 30 (Normalisation Repertoires Series)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 29-films-multi-parties, Plan: 01*
*Completed: 2026-03-01*
