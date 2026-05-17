# Handoff — Courts-métrages + collections (2026-05-17)

## Où on s'est arrêté

Branche : `feat/migrate-nas-raw-mode`
Dernier commit poussé : **`9c8acf9`** — `fix(migrate-nas review): default needs_validation = "k" (keep skip)`
Working tree : **clean**, 1520 tests verts.

## Plan validé avec l'utilisateur

Travail réparti en 5 phases pour ajouter le type "courts-métrages" et les collections (groupement type Looney Tunes).

| Tâche | Statut | Sujet |
|---|---|---|
| #7 | ✅ DONE | UX : `needs_validation` default → `k` (keep skip) — commit 9c8acf9 |
| **#8** | ⏭️ **NEXT** | P1 : `MediaType.SHORT` + setting + classification |
| #9 | pending | P2 : Organizer hiérarchie `Films/Courts métrages/{franchise}/` |
| #10 | pending | P3 : Migration data — reclasser les courts existants en DB |
| #11 | pending | P4 : Modèle `LocalCollection` + suggestion auto |
| #12 | pending | P5 : UI bibliothèque — vue collection |

## Paramètres tranchés par l'utilisateur

| Question | Décision |
|---|---|
| Seuil durée court-métrage | **15 min (900 s)** |
| Hiérarchie storage | **`Films/Courts métrages/...`** (sous Films, pas niveau racine) |
| Sous-classification des courts | **Par franchise** (collection_name TMDB si dispo, sinon "Divers") |
| Règle priorité série | Si fichier sous `Séries/` → reste SERIES (jamais SHORT) |

## P1 — Plan détaillé pour démarrer

### Fichiers à modifier
- `src/core/value_objects/parsed_info.py` : ajouter `SHORT = "short"` à l'enum `MediaType` (l. 22-24)
- `src/config.py` : ajouter `short_film_duration_threshold_seconds: int = Field(default=900, ge=60)` dans Settings (l. 54 voisinage)
- Nouveau helper (location à choisir, probablement `src/services/classification.py` ou dans `core/entities/media.py`) :
  ```python
  def classify_media(parsed_or_path, media_info, threshold_seconds: int) -> MediaType:
      # 1. Si path contient /Séries/, /Series/ → SERIES (priorité absolue)
      # 2. Sinon si media_info.duration_seconds <= threshold → SHORT
      # 3. Sinon → MOVIE
  ```
- Tests TDD : créer `tests/unit/services/test_classification.py`

### Cas de test
1. Film 2h dans Films/ → MOVIE
2. Court 7 min dans Films/ → SHORT
3. Épisode 25 min dans Séries/ → SERIES (priorité chemin sur durée)
4. Court 5 min dans Animations/ → SHORT (Animations ≠ Séries)
5. Durée inconnue (None) → fallback MOVIE par défaut

### Hors scope P1
- Pas de modif Organizer (c'est P2)
- Pas de migration DB (c'est P3)
- Le champ DB sur Movie n'a pas besoin de bouger : on peut classifier dynamiquement via `duration_seconds` existant. Un champ booléen `is_short` peut être ajouté en P2 ou P3 si besoin pour les requêtes filtre.

## Contexte session — choses faites avant l'arrêt

### Diagnostics + fixes des derniers commits
- `df6c7a4` : scanner — filtre catégorie restreint au 1er segment (bug ISX/SeriousImages)
- `c87a61c` : raw_finalizer — fallback film restreint à Animations/ (bug Shadoks → western)
- `9c8acf9` : review — default `needs_validation` = `k`

### Nettoyage manuel fait (pas dans git)
- Fichier `/media/NAS64/Films/Western/A-C/Le Cavalier du désert (1940).mkv` (= en réalité Les Shadoks S3, 642 MB) → restauré vers `/media/wd10-3/Vidéothèque12/Séries/Les SHADOKS - S01 à S04 - TvRip - HEVC - Fr - [Tisoon]/Les Shadoks - S3 (1972) vf - [Tisoon].mkv`
- 4 décisions Shadoks dans `migration/plan.json.state.sqlite` → reset (DELETE FROM migration_decisions/items WHERE item_id IN (...))
- Entry corbeille id=213 "Le Cavalier du désert" → supprimée (faux match)

### Toto reste en corbeille
- Entry corbeille id=214 "Les Blagues de Toto" (2020) — fichier physique encore présent à `/media/NAS64/Films/Comédie/A-H/Bi-Bu/Les Blagues de Toto (2020).mkv`. L'utilisateur peut vider via l'UI quand il veut.

## Comment reprendre après /clear

```
Reprends depuis le handoff .paul/HANDOFF-2026-05-17-courts-metrages.md. On vient de finir la tâche #7 (default needs_validation → k, commit 9c8acf9 poussé). On attaque maintenant #8 : P1 — MediaType.SHORT + setting + classification.
```

Le détail P1 (fichiers à toucher, cas de test, hors scope) est dans la section "P1 — Plan détaillé pour démarrer" ci-dessus.
