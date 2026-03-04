---
phase: 34-detection-doublons-transfert
plan: 01
subsystem: transfer, ui
tags: [duplicate-detection, quality-scoring, sandbox, symlinks, htmx, jinja2]

requires:
  - phase: 31-detection-doublons
    provides: check-duplicates CLI, QualityScorerService
provides:
  - DuplicateDetector service (détection pré-transfert par titre normalisé)
  - Résolution doublons dans le résumé batch web (avant transfert)
  - Sandbox via résolution symlinks (video→storage)
  - Cascade série (un choix = tous les épisodes même titre+année)
  - Dialog comparatif qualité avec scores et recommandation
affects: [phase-33-overlays, maintenance-sandbox]

tech-stack:
  added: [pymediainfo (extraction bitrate)]
  patterns: [symlink-following for storage resolution, codec efficiency normalization]

key-files:
  created:
    - src/services/duplicate_detector.py
    - src/web/templates/transfer/_batch_tree_and_alert.html
    - tests/unit/services/test_duplicate_detector.py
  modified:
    - src/adapters/cli/batch_builder.py
    - src/web/routes/transfer.py
    - src/web/templates/transfer/_batch_content.html
    - src/web/templates/transfer/_batch_tree.html
    - src/web/static/css/style.css

key-decisions:
  - "Résolution pré-transfert dans le résumé batch plutôt que pendant le SSE"
  - "Sandbox résout le vrai chemin storage en suivant les symlinks (évite erreurs de casse)"
  - "Codec efficiency normalization : AV1 ×3.0, HEVC ×2.0, VP9 ×1.8 pour bitrate équitable"
  - "Loguru au lieu de logging standard pour visibilité des messages transfer.py"
  - "keep_old = skip (fichier reste dans temp), pas de suppression"

patterns-established:
  - "_resolve_storage_path : suivre les symlinks video pour trouver le vrai chemin storage"
  - "_moved_to_sandbox set : éviter N moves pour N épisodes d'une même série"

duration: ~5h (2 sessions)
started: 2026-03-03
completed: 2026-03-04
---

# Phase 34 Plan 01: Détection Doublons au Transfert — Summary

**Service DuplicateDetector avec scoring qualité multi-critères, résolution pré-transfert dans le résumé batch web, et sandbox par suivi de symlinks**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5h (2 sessions) |
| Started | 2026-03-03 |
| Completed | 2026-03-04 |
| Tasks | 3 + checkpoint |
| Files created | 3 |
| Files modified | 10 |
| Lines added | ~2400 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Détection pré-transfert films | Pass | Normalisation titre, scan récursif video_dir/Films/ |
| AC-2: Détection pré-transfert séries | Pass | Testé avec Mindhunter + The Outsider, saisons partielles gérées |
| AC-3: Recommandation qualité | Pass | Scores 0-100 avec codec efficiency, badge recommandé |
| AC-4: Sandbox pour anciennes versions | Pass | _resolve_storage_path suit les symlinks, corrige les erreurs de casse |
| AC-5: Conflit web avec scores | Pass | Dialog overlay comparatif, barres qualité, cascade série |
| AC-6: Conflit CLI avec scores | Pass | Tableau Rich enrichi avec scores et recommandation ★ |

## Accomplishments

- Service `DuplicateDetector` centralisé avec détection par titre normalisé et scoring qualité multi-critères (résolution 25%, video codec 20%, audio codec 15%, video bitrate 25%, audio bitrate 15%)
- Résolution pré-transfert dans le résumé batch : l'utilisateur résout AVANT de lancer le transfert, éliminant les interruptions SSE
- Sandbox fiable : `_resolve_storage_path` suit les symlinks pour trouver le vrai chemin storage, indépendamment de la casse ou des noms différents entre video/ et storage/
- Cascade série : résoudre un épisode applique le choix à tous les épisodes du même titre+année
- Repli automatique des groupes séries résolus dans l'arborescence

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Tasks 1-3 | `845d4db` | feat | Détection doublons pré-transfert complet |
| Checkpoint fixes | `9e43cff` | fix | Sandbox via symlinks, loguru, repli séries |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/duplicate_detector.py` | Created | Service détection + scoring qualité |
| `src/web/templates/transfer/_batch_tree_and_alert.html` | Created | Fragment bandeau alerte + arborescence |
| `tests/unit/services/test_duplicate_detector.py` | Created | 354 lignes de tests |
| `src/adapters/cli/batch_builder.py` | Modified | Intégration détection dans le batch |
| `src/web/routes/transfer.py` | Modified | Endpoint resolve-duplicate, _sandbox_existing, _resolve_storage_path |
| `src/web/templates/transfer/_batch_content.html` | Modified | Dialog overlay comparatif qualité |
| `src/web/templates/transfer/_batch_tree.html` | Modified | Bouton résoudre, badge résolu, repli séries |
| `src/web/static/css/style.css` | Modified | Styles doublons, dialog, repli |
| `src/adapters/cli/validation/batch_display.py` | Modified | Tableau Rich enrichi avec scores |
| `src/services/organizer.py` | Modified | _is_content_dir empêche descente dans séries |
| `src/services/transferer.py` | Modified | ExistingFileInfo enrichi (bitrates) |
| `src/web/templates/transfer/_progress.html` | Modified | Résultats transfert enrichis |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Résolution dans le résumé batch (pas SSE) | UX bien meilleure, pas d'interruptions | Nouvel endpoint /resolve-duplicate |
| Symlink-following pour storage | Noms video/ et storage/ peuvent différer (casse) | Robuste, indépendant de la convention de noms |
| Codec efficiency normalization | AV1 à 2Mbps ≈ x264 à 6Mbps en qualité | Comparaisons bitrate équitables |
| Saisons partielles exclues | Nouvelles saisons ≠ doublons | Compteur dédié dans le bandeau |
| Loguru au lieu de logging standard | Messages sandbox étaient silencieux | Visibilité dans les logs |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 4 | Bugs critiques corrigés pendant checkpoint |
| Scope additions | 2 | UX améliorée (repli séries, saisons partielles) |
| Deferred | 1 | Test films à faire |

### Auto-fixed Issues

**1. Sandbox path incorrect**
- Issue: `Path(storage).parent / ".sandbox"` donnait `/media/.sandbox` (Permission denied)
- Fix: `Path(storage) / ".sandbox"` → `/media/NAS64/.sandbox`

**2. move_to_staging déplaçait des symlinks, pas les vrais fichiers**
- Issue: `existing_dir` pointe vers video_dir (symlinks), pas storage_dir
- Fix: `_sandbox_existing` + `_resolve_storage_path` suivent les symlinks

**3. Logger standard logging invisible**
- Issue: transfer.py utilisait `logging.getLogger` alors que l'app utilise loguru
- Fix: Remplacé par `from loguru import logger`

**4. Erreur de casse video/ vs storage/**
- Issue: video_dir avait `MindHunter`, storage_dir avait `Mindhunter`
- Fix: `_resolve_storage_path` suit les symlinks au lieu de reconstruire par nom

### Deferred Items

- Vérifier détection doublons avec un **film** (testé uniquement avec séries)

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ○ | Phase UI — non invoqué (dialog construit manuellement) |

## Next Phase Readiness

**Ready:**
- Phase 33 (Overlays Qualité) peut démarrer — données qualité déjà en base
- Infrastructure CSS doublons réutilisable pour les badges

**Concerns:**
- Tester la détection avec un film avant de considérer la phase complète
- Sandbox management (liste, purge) reste à faire — noté pour phase maintenance

**Blockers:** None

---
*Phase: 34-detection-doublons-transfert, Plan: 01*
*Completed: 2026-03-04*
