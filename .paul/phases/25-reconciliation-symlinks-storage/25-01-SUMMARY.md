---
phase: 25-reconciliation-symlinks-storage
plan: 01
subsystem: cli, services
tags: [symlinks, repair, reconciliation, tvdb, metadata]

requires:
  - phase: 12-dette-technique-donnees
    provides: enriched TVDB episode titles
  - phase: 14-workflow-fluide
    provides: repair service with file indexer
provides:
  - Commande CLI `reconcile` avec 3 phases de réconciliation
  - Recherche métadonnées DB dans RepairService
  - Mise à jour automatique file_path DB
  - Renommage symlinks épisodes avec titres TVDB

affects: [v1.8-robustesse-workflow]

tech-stack:
  added: []
  patterns: [index mémoire O(1) par dict pour matching rapide, Phase 0 DB↔storage]

key-files:
  created: [src/adapters/cli/commands/reconcile_command.py]
  modified: [src/services/repair/repair_service.py, src/adapters/cli/commands/__init__.py, src/main.py]

key-decisions:
  - "Phase 0 ajoutée : réconciliation DB file_path NULL/périmés avant symlinks cassés"
  - "Index rapide par dictionnaires O(1) au lieu de rglob linéaire"
  - "db_session optionnel dans RepairService pour compatibilité tests"

patterns-established:
  - "Pattern index rapide : dict {name → Path} + {clean_title → [Paths]} pour matching O(1)"
  - "Pattern Phase 0 : vérifier cohérence DB↔filesystem avant réparation symlinks"

duration: ~120min
started: 2026-02-28T14:00:00Z
completed: 2026-02-28T17:00:00Z
---

# Phase 25 Plan 01: Réconciliation Symlinks/Storage Summary

**Commande CLI `reconcile` à 3 phases : réconciliation DB↔storage (file_path NULL), réparation symlinks cassés via métadonnées DB + index rapide, renommage 1084 symlinks épisodes avec titres TVDB enrichis.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~120 min |
| Started | 2026-02-28 14:00 |
| Completed | 2026-02-28 17:00 |
| Tasks | 3 completed |
| Files modified | 4 (+1 created) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Recherche métadonnées films | Pass | `_find_by_metadata()` + `_find_movie_by_metadata()` dans RepairService |
| AC-2: Recherche métadonnées séries | Pass | `_find_episode_by_metadata()` cherche par titre+saison+épisode |
| AC-3: Mise à jour file_path DB | Pass | Phase 0 : 185 films + 240 épisodes réconciliés (1ère passe) |
| AC-4: Commande CLI reconcile | Pass | `--dry-run` et mode effectif fonctionnels, rapport Rich |
| AC-5: Mise à jour symlinks titres TVDB | Pass | 1084 épisodes renommés avec titres TVDB enrichis |

## Accomplishments

- **Phase 0 (DB↔storage)** : Réconcilié 185/252 films et 240/347 épisodes avec file_path NULL — films "sans fichier" réduits de 234 à 65
- **Phase 1 (symlinks cassés)** : Réparé 231/331 symlinks cassés (5 via métadonnées DB, 226 via index rapide) — 100 restants irréductibles (fichiers source supprimés)
- **Phase 2 (titres épisodes)** : Renommé 1084 symlinks épisodes avec titres TVDB enrichis (ex: "S02E13 - MULTi" → "S02E13 - La sixième clé")
- **Performance** : Index rapide par dictionnaires O(1) au lieu de rglob linéaire — exécution en secondes au lieu de minutes

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/cli/commands/reconcile_command.py` | Created (699 lines) | Commande CLI reconcile : 3 phases, --dry-run, --update-titles |
| `src/services/repair/repair_service.py` | Modified (+247 lines) | _find_by_metadata(), _find_movie/episode_by_metadata(), _search_file_in_storage() |
| `src/adapters/cli/commands/__init__.py` | Modified | Import + export reconcile |
| `src/main.py` | Modified | Enregistrement app.command()(reconcile) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Ajout Phase 0 (DB↔storage) | Le problème Wadjda a révélé que beaucoup d'entrées DB ont file_path NULL alors que le fichier existe | Résout 185 films + 240 épisodes supplémentaires |
| Index rapide par dictionnaires | rglob de 54754 fichiers × 331 symlinks = trop lent sur disques réseau | O(1) lookups, exécution en secondes |
| db_session optionnel | Tests existants ne fournissent pas de session DB au RepairService | Pas de régression, _find_by_metadata retourne [] sans session |
| guessit pour extraction MediaInfo | Réutiliser le parser existant plutôt que regex ad hoc pour codecs/résolution | Extraction fiable des métadonnées techniques des noms de fichiers |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | Phase 0 ajoutée — résout un problème majeur non anticipé |
| Auto-fixed | 4 | Corrections techniques essentielles |

**Total impact:** Phase 0 est l'ajout le plus significatif — résout le problème racine (file_path NULL) plutôt que juste les symptômes (symlinks cassés).

### Scope Addition: Phase 0 (DB↔storage)

- **Discovered during:** Investigation du problème Wadjda
- **Issue:** 252 films et 347 épisodes avaient file_path NULL en DB alors que les fichiers existent dans storage
- **Addition:** Méthode `_reconcile_db_file_paths()` qui indexe storage et met à jour les file_path DB
- **Result:** 185 films + 240 épisodes réconciliés

### Auto-fixed Issues

**1. Test regression - get_session() en contexte test**
- **Found during:** Task 1
- **Issue:** `_find_by_metadata()` appelait `get_session()` qui connectait à la DB de production
- **Fix:** Paramètre `db_session` optionnel dans constructeur RepairService
- **Verification:** Tests passent sans accès DB

**2. Import MediaInfo incorrect**
- **Found during:** Task 2 (--update-titles)
- **Issue:** `from src.core.value_objects.parsed_info import MediaInfo` — mauvais module
- **Fix:** `from src.core.value_objects.media_info import ...`

**3. VideoCodec/AudioCodec traités comme enums**
- **Found during:** Task 2 (--update-titles)
- **Issue:** `VideoCodec.HEVC` — ce sont des dataclasses, pas des enums
- **Fix:** `VideoCodec(name="HEVC")`, `AudioCodec(name="DTS")` etc.

**4. Settings.trash_dir inexistant**
- **Found during:** Task 2
- **Issue:** `config.trash_dir` n'existe pas dans le modèle Settings
- **Fix:** Supprimé trash_dir du constructeur RepairService dans reconcile

### Deferred Items

- Supprimer l'option "migré" de la liste des lecteurs (UI, hors scope)
- Ajouter option de réinitialisation workflow depuis l'interface web (UI, hors scope)
- ~100 symlinks cassés irréductibles (fichiers source supprimés du storage)
- ~65 films sans file_path restants (pas de correspondance trouvable)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Performance 331×54754 linéaire | Index rapide par dictionnaires O(1) |
| file_path NULL non anticipé dans le plan | Phase 0 ajoutée pour réconciliation DB↔storage |
| guessit résolution/codec extraction | Utilisation de guessit natif + constructeurs dataclass |

## Skill Audit

`/frontend-design` est "required" pour les phases UI — cette phase est purement backend (services, CLI). Non applicable. ✓

## Next Phase Readiness

**Ready:**
- Commande `reconcile` opérationnelle avec 3 phases de réconciliation
- RepairService enrichi avec recherche métadonnées DB
- 1084 symlinks épisodes mis à jour avec titres TVDB

**Concerns:**
- 100 symlinks cassés irréductibles (fichiers supprimés)
- 65 films sans file_path restants

**Blockers:**
- None — Phase 25 et milestone v1.7 complètes

---
*Phase: 25-reconciliation-symlinks-storage, Plan: 01*
*Completed: 2026-02-28*
