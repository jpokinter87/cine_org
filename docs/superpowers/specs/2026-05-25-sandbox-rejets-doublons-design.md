# Sandbox : correctif « Garder l'ancien » + gestion enrichie

**Date :** 2026-05-25
**Statut :** Conçu, en attente de validation utilisateur
**Branche :** `feat/migrate-nas-raw-mode`

## Contexte et problème

Lors d'un traitement, le `DuplicateDetector` détecte qu'un titre existe déjà dans
la vidéothèque et propose une résolution (`keep_old` / `keep_new` / `keep_both` /
`skip`). Quand l'utilisateur choisit **« Garder l'ancien » (`keep_old`)**, le code
de `_run_web_transfer` (`src/web/routes/transfer.py:604-610` pour la pré-résolution,
`:804-810` pour la résolution SSE) **se contente de sauter le transfert** :

```python
if pre_resolution == "keep_old":
    progress.conflicts_resolved += 1
    progress.message = f"Doublon résolu (pré) : ancien conservé pour {display_name}"
    await asyncio.sleep(0.1)
    continue            # ← le nouveau fichier reste dans downloads/
```

Le nouveau fichier téléchargé n'est jamais retiré de `downloads/`. Or chaque
traitement :
1. efface toute la DB intermédiaire (`workflow.py:99-106`),
2. **re-scanne `downloads/`** (`scanner.py`, `file_system.py:262-266` ne saute que
   les hardlinks de seeding `st_nlink > 1` et les symlinks),
3. re-matche, re-crée les pending, et le `DuplicateDetector` re-détecte le doublon.

**Résultat :** une série comme « Octobre » (version existante AV1 préférée) est
re-proposée à chaque traitement, indéfiniment. L'utilisateur répète son choix en
vain.

À l'inverse, **« Garder le nouveau » (`keep_new`)** *déplace* le fichier (transfert
vers `storage/`), donc il quitte `downloads/` et n'est plus re-détecté. C'est ce
mécanisme de « sortie de `downloads/` » qui manque à `keep_old`.

### Problème secondaire découvert

`SandboxService.list_sandboxed()` (`src/services/sandbox_service.py:91-120`) ne
scanne que `sandbox/orphans/`. Or `_sandbox_existing()` (`transfer.py:186-264`)
dépose les **anciennes versions remplacées** à la racine `sandbox/<arborescence>`,
hors de `orphans/`. Ces fichiers **n'apparaissent jamais** dans l'UI de maintenance
et ne peuvent pas y être supprimés.

## Objectifs

1. **Correctif** : « Garder l'ancien » déplace le nouveau fichier rejeté hors de
   `downloads/` vers le sandbox (réversible), pour qu'il ne soit plus re-détecté.
2. **Gestion enrichie du sandbox** (section `/maintenance` existante) :
   - lister **tous** les fichiers sandboxés (orphelins + anciennes versions +
     doublons rejetés + legacy), pas seulement `orphans/` ;
   - **catégoriser** chaque fichier par origine (badge + filtre) ;
   - **garde-fou « version conservée »** : indiquer pour chaque fichier si une
     autre copie existe dans la vidéothèque (vert) ou non (rouge = potentiellement
     unique) ;
   - **suppression définitive** facile et sûre : overlay de confirmation enrichi
     (nombre, taille totale libérée, liste des noms, avertissement renforcé si un
     fichier est en rouge). La suppression reste un `unlink` direct, restreint à la
     machine maître, protégé par `_is_inside_sandbox`.

## Non-objectifs (YAGNI)

- Pas de corbeille intermédiaire pour le sandbox (suppression = `unlink` direct).
- Pas de confirmation forte (taper le nombre, etc.).
- Pas de page dédiée `/sandbox` : on étend la section existante de `/maintenance`.
- Pas de manifeste de provenance persisté (cf. Approche 2 écartée ci-dessous).

## Structure de sandbox catégorisée

Trois sous-dossiers, un par origine. La catégorie se **déduit du sous-dossier de
premier niveau** — aucune persistance nouvelle.

| Sous-dossier | Catégorie | Base de l'`original_path` | Déposé par |
|---|---|---|---|
| `orphans/` | `orphelin` | `storage_dir` | `SandboxService.sandbox_orphans` (inchangé) |
| `anciennes_versions/` | `ancienne_version` | `storage_dir` | `_sandbox_existing` (cible **modifiée**) |
| `rejets_doublons/` | `rejet_doublon` | `downloads_dir` | **nouveau** (correctif) |
| *(racine, legacy)* | `autre` | `storage_dir` | anciens dépôts `_sandbox_existing` |

Constantes de noms de sous-dossiers définies dans `SandboxService` pour éviter la
duplication de chaînes magiques.

## Décision technique : garde-fou « version conservée » (Approche 1)

**Approche retenue — vérification live indexée.**

Au chargement de la page maintenance, `SandboxService` construit **une seule fois**
un index de `video/` :
- **Films** : ensemble de titres normalisés (+ année) présents dans `video/Films/`.
- **Séries** : dict `titre normalisé → set("SxxExx")` présents dans `video/Series/`.

La normalisation réutilise `_normalize_title()` et la regex `SxxExx` de
`src/services/duplicate_detector.py` (DRY — pas de logique dupliquée).

Pour chaque fichier sandboxé, on dérive titre/année/épisode depuis son chemin
relatif (le composant `Titre (AAAA)` pour le titre+année ; la regex `SxxExx` sur le
nom de fichier pour l'épisode), puis on teste l'appartenance à l'index :
- film présent → `kept_version` = chemin relatif du dossier trouvé dans `video/`,
- épisode présent dans le set de la série → `kept_version` = chemin,
- sinon → `kept_version = None` (rouge).

**Avantages :** aucune persistance, fonctionne pour toutes les catégories (y
compris orphelins et legacy), et **détecte le cas dangereux** où la version
« conservée » a été supprimée depuis le sandboxing. Un seul parcours de `video/`.

**Approche 2 écartée — manifeste de provenance JSON.** Enregistrer
`{catégorie, version_conservée}` au sandboxing. Plus direct pour les doublons, mais
ajoute une persistance à synchroniser (suppression/réinjection), inutile pour le
legacy, et ne détecte pas la disparition ultérieure de la version conservée.

## Composants et changements

### 1. `src/services/sandbox_service.py`

- Constantes de catégories : `ORPHANS_SUBDIR = "orphans"`,
  `REPLACED_SUBDIR = "anciennes_versions"`, `REJECTED_SUBDIR = "rejets_doublons"`.
- `SandboxedFile` : ajout des champs `category: str` et
  `kept_version: Optional[str]` (chemin relatif dans `video/` ou `None`).
- `list_sandboxed()` : scanne désormais **toute** l'arborescence du sandbox,
  attribue la catégorie selon le sous-dossier de premier niveau, calcule
  `original_path` selon la base de la catégorie (storage ou downloads).
- Nouvelle méthode `sandbox_rejected(paths: list[Path]) -> int` : déplace des
  fichiers de `downloads/` vers `rejets_doublons/`, en préservant l'arborescence
  relative à `downloads_dir` (fallback `path.name` si hors downloads). Même patron
  que `sandbox_orphans` / `reinject_files`.
- Nouvelle méthode `build_video_index(video_dir: Path)` + `find_kept_version(...)`
  (ou une méthode unique `annotate_kept_versions(files, video_dir)`) implémentant
  l'Approche 1.
- `_cleanup_empty_parents` : généraliser pour borner le remontage à la racine du
  sandbox quel que soit le sous-dossier.
- `reinject_files` : déterminer le segment de type (`Films`/`Séries`) relativement à
  la racine de catégorie du fichier (et non plus `_orphans_dir` en dur).

`SandboxService.__init__` reçoit déjà `sandbox_dir, storage_dir, downloads_dir` ; il
faut lui passer `video_dir` (via le container) **ou** passer `video_dir` en argument
des nouvelles méthodes d'indexation. → On passe `video_dir` en **argument de
méthode** (`annotate_kept_versions(files, video_dir)`) pour ne pas changer la
signature du constructeur ni le provider du container.

### 2. `src/web/routes/transfer.py`

- Les deux branches `keep_old` (pré-résolu `:604-610` et SSE `:804-810`) : si
  `not dry_run`, déplacer `source` vers `rejets_doublons/` via
  `SandboxService.sandbox_rejected([source])`. Récupérer le service via un helper
  local (cf. `maintenance._get_sandbox_service`) ou `container.sandbox_service(...)`.
  Logguer le déplacement. En cas d'échec : logguer un warning, ne pas planter le
  transfert (le fichier reste, comportement actuel).
- `_sandbox_existing()` : changer la destination des anciennes versions de
  `sandbox_dir / relative` vers `sandbox_dir / REPLACED_SUBDIR / relative` (films et
  séries), pour qu'elles soient catégorisées et listées.
- `skip` (« Passer ») : **inchangé** (le fichier reste dans `downloads/`).

### 3. `src/web/routes/maintenance.py`

- Les 3 endpoints sandbox (`/maintenance` GET, `/maintenance/sandbox/delete`,
  `/maintenance/sandbox/reinject`, `/maintenance/sandbox/move-orphans`) :
  après `list_sandboxed()`, appeler `annotate_kept_versions(files, video_dir)` et
  exposer `category` + `kept_version` dans `sandbox_items`.
- `_get_sandbox_service` : inchangé (signature constructeur conservée).

### 4. UI — `src/web/templates/maintenance/_sandbox_section.html` + `index.html`

- Nouvelle colonne **Catégorie** : badge couleur par catégorie
  (orphelin / ancienne version / doublon rejeté / autre).
- Nouvelle colonne **Version conservée** : ✅ vert + chemin si `kept_version`,
  ⚠️ rouge « aucune trouvée » sinon.
- **Filtre par catégorie** : boutons de filtrage (réutiliser le patron HTMX/JS
  existant ; un simple filtre JS côté client sur les lignes suffit, pas de
  round-trip serveur).
- Overlay de suppression (`sandbox-delete-overlay` dans `index.html`) enrichi :
  nombre de fichiers, **taille totale libérée**, liste des noms, et avertissement
  visuel renforcé si au moins un fichier sélectionné est en rouge.
- CSS : badges de catégorie + indicateurs vert/rouge, dans le style sandbox
  existant (`.sandbox-*`).

## Flux de données

**Correctif keep_old :**
```
Résumé batch → resolve-duplicate(keep_old) → transfer/start
  → _run_web_transfer : branche keep_old
    → SandboxService.sandbox_rejected([source])
      → move downloads/Séries/.../Octobre…x265.mkv
           → sandbox/rejets_doublons/Séries/.../Octobre…x265.mkv
  → prochain traitement : scan downloads/ ne trouve plus le fichier ✓
```

**Affichage sandbox :**
```
GET /maintenance
  → list_sandboxed() (scan complet, catégorie par sous-dossier)
  → annotate_kept_versions(files, video_dir)
       (index video/ construit une fois → kept_version par fichier)
  → render _sandbox_section.html (badges + vert/rouge)
```

**Suppression :**
```
sélection → overlay (récap : nb, taille, noms, avertissement rouge)
  → POST /maintenance/sandbox/delete (machine maître only)
    → delete_files() (unlink, garde-fou _is_inside_sandbox)
  → re-render section
```

## Gestion des erreurs

- `sandbox_rejected` : fichier source absent → warning, ignoré. Échec move →
  warning, le transfert continue (le fichier rejeté reste dans `downloads/`, donc
  re-proposé au prochain coup — dégradation gracieuse, pas de perte).
- `annotate_kept_versions` : `video/` absent ou illisible → tous `kept_version=None`
  (rouge), jamais d'exception propagée.
- Dérivation titre/épisode impossible depuis le chemin → `kept_version=None`.
- `delete_files` / `reinject_files` : garde-fou `_is_inside_sandbox` déjà en place ;
  tentative hors sandbox loggée en erreur et ignorée.

## Stratégie de test (TDD)

Tests d'abord, dans `tests/unit/test_sandbox_service.py` (existant) et un test web.

1. **Correctif keep_old** (`tests/unit/web/` ou `test_workflow_routes.py` pattern) :
   `_run_web_transfer` avec un transfer `has_duplicate` + `duplicate_resolution=
   "keep_old"` → le fichier source est déplacé sous `rejets_doublons/`, n'est plus
   dans `downloads/`, et `transfer_file` n'est jamais appelé.
2. **`sandbox_rejected`** : déplace en préservant l'arborescence relative à
   downloads ; fallback `path.name` hors downloads ; fichier absent ignoré.
3. **`list_sandboxed` multi-catégories** : fixtures dans `orphans/`,
   `anciennes_versions/`, `rejets_doublons/`, racine → catégories correctes +
   `original_path` correct (base storage vs downloads).
4. **`annotate_kept_versions`** : film présent dans `video/Films/` → `kept_version`
   non `None` ; absent → `None`. Série : épisode présent → non `None` ;
   épisode manquant → `None`.
5. **`_sandbox_existing`** : la cible est bien `anciennes_versions/` (films et
   séries / épisode unique).
6. **Non-régression** : `delete_files` et `reinject_files` fonctionnent sur les
   nouvelles catégories ; `_cleanup_empty_parents` borne au sandbox.

Mocks : `MagicMock` pour le container/transferer (le keep_old ne transfère pas),
`tmp_path` pour les arborescences sandbox/downloads/video réelles.

## Documentation

Mettre à jour `README.md` : section sandbox/maintenance — catégories, garde-fou
« version conservée », et comportement « Garder l'ancien » (le rejet part en
sandbox, supprimable depuis Maintenance).

## Fichiers impactés

- `src/services/sandbox_service.py` (catégories, `sandbox_rejected`, index, list)
- `src/web/routes/transfer.py` (keep_old → sandbox_rejected ; `_sandbox_existing` →
  sous-dossier `anciennes_versions/`)
- `src/web/routes/maintenance.py` (annotation kept_version dans les 3 endpoints)
- `src/web/templates/maintenance/_sandbox_section.html` (colonnes badge + vert/rouge,
  filtre)
- `src/web/templates/maintenance/index.html` (overlay enrichi, CSS/JS)
- `tests/unit/test_sandbox_service.py` + nouveau test web keep_old
- `README.md`
