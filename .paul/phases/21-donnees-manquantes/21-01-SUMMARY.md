---
phase: 21-donnees-manquantes
plan: 01
subsystem: cli
tags: [matching, fuzzy, normalization, unicodedata, difflib]

requires:
  - phase: 20-navigation-affichage
    provides: navigation améliorée et genres normalisés
provides:
  - Commande link-movies améliorée avec 4 stratégies de matching progressif
  - 1040 films liés (82.5% des 1260 sans file_path)
  - 1036 films enrichis techniquement via enrich-tech
affects: [21-02 (épisodes sans titres), 22 (suppression bibliothèque)]

tech-stack:
  added: []
  patterns: [matching progressif normalisé→substring→contains→fuzzy, index mémoire par année]

key-files:
  created: []
  modified:
    - src/adapters/cli/commands/import_commands.py

key-decisions:
  - "Seuil fuzzy 0.85 — bon équilibre vrais/faux positifs"
  - "Index mémoire par année pour performance O(1) au lieu de requêtes DB par symlink"
  - "Normalisation NFKD + suppression articles multilingues"
  - "4 stratégies progressives : normalized, substring, contains, fuzzy"

patterns-established:
  - "_normalize_for_match() : normalisation NFKD, suppression accents, minuscules, suppression articles"
  - "Index pré-chargé movies_by_year pour matching batch performant"

duration: ~30min
started: 2026-02-27
completed: 2026-02-27
---

# Phase 21 Plan 01: Résolution Films sans file_path — Summary

**Commande link-movies améliorée avec matching normalisé + fuzzy : 1040 films liés (82.5%), 1036 enrichis techniquement**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 2 completed (1 auto + 1 checkpoint) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Matching normalisé ("La Zone d'intérêt") | Pass | Film lié avec succès, métadonnées techniques peuplées |
| AC-2: Matching insensible casse/accents | Pass | Normalisation NFKD + lowercase résout tous les cas |
| AC-3: Matching avec sous-titre dans le nom | Pass | Stratégie substring (split sur ` - `) + contains |
| AC-4: Réduction > 60% des 1260 films | Pass | 1040/1260 = 82.5% (objectif 60% largement dépassé) |
| AC-5: Enrichissement technique post-liaison | Pass | 1036 films enrichis via enrich-tech |

## Accomplishments

- **1040 films liés** : de 1260 sans file_path à 220 restants (22% → 3.9% du total)
- **4 stratégies de matching progressif** : normalized (accents, casse, articles), substring (titre avant ` - `), contains (titre ≥5 chars dans le nom de fichier), fuzzy (SequenceMatcher ≥ 0.85)
- **1036 films enrichis** techniquement (resolution, codecs, langues) via enrich-tech
- **La Zone d'Intérêt** : résolu — resolution=1920x1080, codec_video=x265, codec_audio=AAC, languages=fr/de

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1: Matching normalisé + fuzzy | (à committer) | feat | _normalize_for_match + _try_match_movie + index par année |
| Task 2: Checkpoint human-verify | — | verify | Exécution link-movies + enrich-tech confirmée |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/cli/commands/import_commands.py` | Modified | _normalize_for_match(), _try_match_movie(), réécriture _link_movies_async() avec matching progressif |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Seuil fuzzy 0.85 | Analyse des 220 restants confirme : 0.85 évite les faux positifs (Anina/Marina, Black Box/Black Widow) | Seuil validé pour le futur |
| Index mémoire par année | Évite N requêtes DB pour N symlinks — toutes les données chargées une fois | Performance batch optimale |
| 4 stratégies progressives | Chaque stratégie attrape un type de mismatch spécifique | Couverture maximale sans faux positifs |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 1 | Analyse des 220 restants (diagnostic post-exécution) |
| Deferred | 1 | Normalisation ponctuation pour ~10 films supplémentaires |

**Total impact:** Diagnostic utile, pas de scope creep

### Analyse des 220 films restants

Diagnostic post-exécution demandé par l'utilisateur. Résultats :

| Catégorie | Nombre | Explication |
|-----------|--------|-------------|
| Match potentiel (0.70-0.84) | 22 | ~10 vrais matchs (ponctuation : `:·?` → `-...`), ~12 faux positifs |
| Titre trop différent / absent | 197 | Making-of (~15), titres courts/génériques (~30), titre FR≠fichier (~40), films sans fichier physique (~100+) |
| Sans année en base | 1 | "Morse" |

**Récupérable :** ~10-12 films supplémentaires via normalisation de ponctuation (`:` `·` `?` → tiret/espace). Candidat pour un plan 21-03 optionnel.

**Non récupérable :** La majorité des 197 sont des films en base TMDB sans fichier physique correspondant — le matching ne peut rien y faire.

## Skill Audit

/frontend-design (required) : Non applicable — phase purement CLI/data, aucun template HTML modifié ✓

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Dry-run affichait 1365 matchs > 1260 films | Normal : sans écriture réelle, même film matché par plusieurs symlinks. En exécution réelle : 1040 (premier match gagne) |

## Next Phase Readiness

**Ready:**
- 220 films restants analysés et catégorisés
- Stratégie de matching prouvée et réutilisable
- Phase 21 plan 02 à créer : épisodes sans titres (383) et séries sans tvdb_id (18)

**Concerns:**
- Les 197 films "titre trop différent" sont majoritairement sans fichier physique — irrésoluble par le matching

**Blockers:**
- None

---
*Phase: 21-donnees-manquantes, Plan: 01*
*Completed: 2026-02-27*
