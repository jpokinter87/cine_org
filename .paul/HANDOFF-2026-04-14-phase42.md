# Handoff — Phase 42-01 Overrides Hors Canon (pause après Task 1)

**Date :** 2026-04-14
**Commit :** 63ee104 (master, non pushé)
**Phase :** 42 — Overrides Manuels
**Plan en cours :** 42-01 — Épisodes hors canon

## Ce qui est fait

**Task 1/3 complète** : socle DB livré et testé
- `SeasonOverrideModel` (table `season_overrides`) avec index unique
  composite `(tvdb_id, season_number)`
- Colonne `is_extra` sur `EpisodeModel` + migration 10 dans `database.py`
- Tests : 5/5 verts (`tests/unit/test_season_override.py`)
- Non-régression persistence : 6/6 verts

## Ce qui reste (tâches 2 et 3 du plan 42-01)

### Task 2 — Override consulté dans les 2 filtres d'épisodes

Fichiers à modifier :
- `src/services/workflow/pending_factory.py::filter_by_episode_count`
  — ajouter paramètre `session: Optional[Session] = None`, lire
  `SeasonOverrideModel`, faire `count = max(count or 0, override.episode_count)`
- `src/services/workflow/pending_factory.py::create_pending_validation`
  — propager `session`
- `src/adapters/cli/auto_validator.py::_filter_by_episode_count_compatibility`
  — même pattern
- `src/adapters/cli/auto_validator.py::auto_validate_files` — propager
- Callsites :
  - `src/services/workflow/matching_step.py::_create_pending_validation`
    passe `self._container.session()` (vérifier nom exact dans `container.py`)
  - `src/web/routes/workflow.py::_run_web_workflow` passe
    `pending_repo._session` (déjà dispo)

Tests à ajouter dans `tests/unit/test_pending_factory.py` (créer ou
compléter) : 4 cas (sans override, avec override qui accepte,
override inférieur au canon, session=None fallback).

### Task 3 — Détection + section anomalies dans le résumé workflow

**⚠️ Charger `/frontend-design` avant cette tâche.**

À créer :
- `src/services/anomaly_detector.py` avec classe `AnomalyDetector` et
  dataclass `ExcessEpisodeGroup` (algo : grouper pendings par
  `(top_tvdb_candidate, season)` où `episode > tvdb_count`)

À modifier :
- `src/web/routes/workflow.py` :
  - Ajouter `anomaly_groups: list` sur `WorkflowProgress`
  - Appeler `AnomalyDetector.find_excess_episode_groups()` en fin de
    `_run_web_workflow`
  - 3 nouvelles routes : `POST /workflow/anomalies/{accept,dismiss,trash}`
- `src/web/templates/workflow/_results.html` : ajouter section
  conditionnelle « Cas particuliers à traiter » avec un bloc par groupe
  (3 boutons HTMX, signal « N saisons déjà validées »)
- `src/adapters/cli/batch_builder.py` : positionner `is_extra=True` à
  la création d'`EpisodeModel` quand `episode_num > tvdb_canonical_count`

Tests :
- `tests/unit/test_anomaly_detector.py` (4 cas)
- `tests/unit/test_workflow_routes.py` (4 cas : accept/dismiss/trash/idempotence)

## Vérification fonctionnelle finale (après task 3)

*The Big C* S04E05-E08 dans `/downloads` :
1. Lancer workflow web → épisodes en pending (bloqués par les filtres)
2. Voir bloc « The Big C — Saison 4 » dans le résumé
3. Cliquer « Accepter comme découpage alternatif »
4. Vérifier : `SELECT * FROM season_overrides` → (246063, 4, 8) ;
   pendings VALIDATED ; `EpisodeModel.is_extra=1`

## Commandes de reprise

```bash
cd /home/jp/PythonProject/cine_org
uv sync --extra dev
uv run pytest tests/unit/test_season_override.py -v  # baseline ok
```

Pour relancer :
```
/paul:apply .paul/phases/42-overrides-manuels/42-01-PLAN.md
```

## Rappels importants

- **`uv run pytest` nécessite `uv sync --extra dev` en préfixe** — pytest
  est dans l'extra `dev` du pyproject (voir mémoire
  `tests_command.md`).
- Ne jamais `git push` sans accord explicite — commit 63ee104 reste
  local pour l'instant.
- Skill `/frontend-design` **requis** avant la tâche 3 (modif template).

## Plan 42-02 (overrides métadonnées) — non commencé

Concerne : édition manuelle d'affiche/synopsis/casting depuis la fiche
web, stockage dans `storage/.metadata/`, flag `preserve_overrides` pour
l'enricher. À planifier après clôture du 42-01.
