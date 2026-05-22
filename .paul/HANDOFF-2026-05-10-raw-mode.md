# PAUL Handoff — Mode raw migration NAS

**Date :** 2026-05-10 (session après-midi)
**Status :** paused — mode raw 100 % livré, apply en cours sur /media/wd10-1

---

## READ THIS FIRST

Cette session a livré l'**extension mode raw** du package migration et a démarré la **validation prod** sur un vrai vieux NAS (`/media/wd10-1`). L'apply tourne toujours côté utilisateur quand on s'arrête (~80 GB pending à ~40 MB/s, ETA ~33 min en mode `--fast`).

Le matin de la même journée a vu la livraison du **mode symlinks pur** (PR #1 mergée via squash sur master, commit `8e7ec1c`). Voir HANDOFF-2026-05-10.md (matin) pour le contexte de cette livraison.

**Projet :** CineOrg — gestion de vidéothèque personnelle.
**Core value :** Organiser et renommer automatiquement une vidéothèque depuis les téléchargements.

---

## Current State

**Version :** 2.1.0-dev
**Milestone :** v2.1 Lecteurs Externes & Intégrations (75 % — 3/4 phases)
**Branche :** `feat/migrate-nas-raw-mode` (~25 commits ahead of master, tous pushés)
**Phase formelle PAUL :** 43 close depuis 2026-04-14, mode raw livré hors flow PAUL (suite de la refonte).

**Loop Position :**
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     (mode raw livré, apply en cours côté utilisateur)
```

---

## What Was Done (cette session)

### 1. Mode raw migration — 5 étapes principales (commits 17d23ae → 1ecb307)

- **Étape 1** (`17d23ae`) : Bucket.NEEDS_VALIDATION + MatchInfo + is_symlink_source dans dataclasses
- **Étape 2** (`ca53203`) : MigrationMatcher (TMDB+TVDB scoring 85 %)
- **Étape 3** (`3718b36`) : plan_builder mode raw + needs_validation.csv
- **Étape 4a** (`62ebd6a`) : transfer_executor + Protocol RawItemFinalizer
- **Étape 4b1/2/3** (`6231d99` + `5659f66` + `6c48c4f`) : MigrationRawFinalizer films + séries + finalize end-to-end
- **Étape 5** (`1ecb307`) : CLI `--include-raw` + DefaultDetailsFetcher + wiring container + README

### 2. Améliorations matcher (post-diagnostic 1er run)

- **Tie-break année** (`ecb1011`) : récupère ~10 cas "top trop serrés" (The Leftovers etc.)
- **Bucket ALREADY_IN_LIBRARY** + LibraryPresenceChecker (`903bfbe`) : skip œuvres déjà en DB
- **Fallback titre tronqué** (`6838e56`) : récupère "Rivalité de génies 02 ..." → "Rivalité de génies"
- **Tentative routage path-prioritaire** (`97a4f54`) → **revert** (`e18cfcf`) car régression sur films d'animation rangés en Animations/

### 3. Bug fixes apply (cause de la galère UX)

- **Filtre scanner par catégorie** (`872d84c`) : Films/Séries/Animations par défaut, --all-categories opt-out
- **Barre progression Rich plan** (`0807658`) + **légende buckets** (`01922d7`)
- **Barre progression Rich apply** (`1d3f2c6`)
- **Streaming rsync progress2** (`aac51ad`) : capture --info=progress2 en live
- **Events hashing_source/dest** (`6079991`) : feedback pendant les calculs xxh3_64
- **Retrait bwlimit défaut** (`c5656b4`) : 25M → 0 (no limit) en 1er essai
- **--outbuf=L** (`fe32f48`) : force line buffering rsync (mais retiré ensuite)
- **stderr→stdout** (`57dc98b`) : évite blocage Popen sur buffer stderr saturé
- **Défaut bwlimit shadow** (`f67f1c8`) : `run_apply` avait son propre default hardcodé qui shadow `_DEFAULT_BANDWIDTH_STEPS_MBPS` — corrigé
- **Parser progress2 locale fr** (`c256bbc`) : `[\d,]+` → `[\d.,]+` pour accepter "677.216.256" (séparateur fr)
- **Sous-barre fichier en cours** (`e6bdbdd`) : 2e Progress task avec progression au fichier (octets/octets) + ETA spécifique
- **Flag `--fast`** (`c8c14af`) : skip xxh3_64 source+dest (gain ~50 % du temps total)

### 4. Validation prod sur /media/wd10-1

- **Plan #1** : 163 items (filtre catégories : Films/Séries/Animations sous Vidéothèque10/)
- **Run 2** (avec améliorations matcher) : 27 MIGRATE / 91 GB / 13 ALREADY_IN_LIBRARY (28 GB économisés) / 108 NEEDS_VALIDATION
- **Apply en cours** : Marius (4.6 GB) committed du 1er run incomplet, La.Flor partie 3 en cours de transfert
- **Diagnostic réseau** : NAS Synology bride à ~40 MB/s en écriture (pas le mount, pas le réseau gigabit, c'est le hardware NAS lui-même)

### 5. Tests TDD

161 tests dans le package migration (vs 73 au début de session) + 1383 tests globaux verts. Zéro régression à chaque commit.

---

## What's In Progress

**Côté utilisateur** : `cineorg migrate-nas apply ./migration/plan.json --fast` tourne avec ~30-40 min restantes pour ~80 GB de transferts à ~40 MB/s soutenu (bottleneck NAS hardware).

Une fois apply terminé :
- 16 fichiers transférés (Marius + 15 autres MIGRATE)
- DB peuplée avec leurs Movie/Series/Episode
- Symlinks créés dans `<video_dir>/Films/...` et `<video_dir>/Séries/...`
- Sources supprimées de `/media/wd10-1`

---

## What's Next

**Immédiat (post-apply) :**
1. Vérifier sur disque : symlinks créés correctement dans video/, fichiers présents dans storage/
2. Vérifier en DB : Movies/Series/Episodes insérés avec file_path/symlink_path
3. Inspecter `already_in_library.csv` (13 items, ~28 GB) — supprimer manuellement les sources de `/media/wd10-1` qui sont déjà en bibliothèque
4. Inspecter `needs_validation.csv` (108 items) — retraiter via `cineorg process` au prochain workflow standard

**Ensuite — clôture du cycle migration NAS :**
5. Si tests prod OK → ouvrir une PR pour `feat/migrate-nas-raw-mode` (mode raw + UX fixes)
6. Une fois mergée → on peut s'attaquer aux autres anciens NAS de l'utilisateur via le même flow

**Ensuite — milestone v2.1 :**
7. `/paul:plan` pour la **phase 41 Jellyfin** (volumes Docker, montage symlinks+cibles) — clôt v2.1.

---

## Décisions techniques de cette session

**Mode raw — architecture** :
- Pattern read-only préservé : pas d'insert DB pendant `plan` (déféré à apply)
- `MigrationMatcher` réutilise `MatcherService` du workflow standard (DRY)
- `LibraryPresenceChecker` court-circuite avant fetcher (économie API si déjà en DB)
- `MigrationRawFinalizer` Protocol injectable, implémentation concrète câblée par CLI
- `RsyncRunner.run` étendu avec `on_progress` pour streaming progress2 (rétrocompat préservée)

**Mode raw — production** :
- Flag `--fast` (`verify_hash=False`) pour skip xxh3_64 source+dest. Reprise basée sur taille au lieu de hash.
- Filtrage par catégorie : préfixes `("film", "seri", "anim")` insensibles casse+accents, segmentation sur tous les segments du chemin.
- Routage film/série : `parsed.media_type` reste autoritaire (override path testé puis rejeté car régression sur films-d'animation rangés sous Animations/).
- bwlimit défaut : `(0, 50, 25, 10, 5)` MB/s. 1er essai sans limite, retry dégressif si erreur réseau.

**Apply UX** :
- Sous-barre Rich par fichier (octets transférés / taille totale + ETA spécifique) en plus de la barre globale (items totaux).
- Phases visibles : preparing → hashing_source → copying_Nmbps (ou rsync progress) → verifying → finalizing → committed.
- Légende buckets affichée avant la barre `plan`.

**rsync subprocess** :
- `stderr=subprocess.STDOUT` (évite blocage buffer stderr saturé sur Popen)
- Parser `--info=progress2` accepte les locales fr/en (séparateurs `.` ou `,` dans les nombres)
- Pas de `--outbuf=L` ni `--no-inc-recursive` (testés inutiles, retirés)

---

## Commits cette session (sur feat/migrate-nas-raw-mode)

Branche à 25 commits au-dessus de master. Stack chronologique (récent → ancien) :

```
c8c14af feat(migration): flag --fast (skip hashs)
e6bdbdd feat(migration): sous-barre Rich par fichier
c256bbc fix(migration): parser progress2 locale fr
f67f1c8 fix(migration): défaut hardcodé bwlimit shadow
57dc98b fix(migration): rsync stderr→stdout + diag
fe32f48 fix(migration): --outbuf=L (retiré ensuite)
c5656b4 fix(migration): retire bwlimit défaut
6079991 fix(migration): events hashing
aac51ad fix(migration): rsync streaming + escape balises
1d3f2c6 feat(migration): barre Rich apply
e18cfcf Revert "fix routage path"
01922d7 feat(migration): légende buckets
97a4f54 fix(migration): routage path (revert)
2457e73 fix(series-repo): get_by_tmdb_id
6838e56 feat(migration): fallback titre tronqué
903bfbe feat(migration): bucket ALREADY_IN_LIBRARY
ecb1011 feat(migration): tie-break année
872d84c feat(migration): filtrage catégories
0807658 feat(migration): barre Rich plan
1ecb307 feat(migration): mode raw — CLI + wiring + README (étape 5/5)
6c48c4f wip(migration): finalize complet (étape 4b3)
5659f66 wip(migration): finalize séries (étape 4b2)
6231d99 wip(migration): finalize films (étape 4b1)
62ebd6a wip(migration): transfer_executor + Protocol (étape 4a)
3718b36 wip(migration): plan_builder mode raw (étape 3)
ca53203 wip(migration): MigrationMatcher (étape 2)
17d23ae wip(migration): dataclasses (étape 1)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `.paul/STATE.md` | État live du projet |
| `.paul/HANDOFF-2026-05-10-raw-mode.md` | **Ce handoff** (mode raw + apply en cours) |
| `.paul/HANDOFF-2026-05-10.md` | Handoff matin (mode symlinks pur, déjà mergé) |
| `src/services/migration/__init__.py` | Re-exports publics |
| `src/services/migration/matching.py` | MigrationMatcher + DefaultDetailsFetcher |
| `src/services/migration/library_presence_checker.py` | Détection œuvres déjà en DB |
| `src/services/migration/raw_finalizer.py` | MigrationRawFinalizer (films + séries) |
| `src/services/migration/transfer_executor.py` | Pipeline rsync + verify + finalize + on_event/on_rsync_progress |
| `src/services/migration/plan_builder.py` | Plan + buckets + CSVs (ajout already_in_library.csv) |
| `src/services/migration/scanner.py` | Filtrage catégories Films/Séries/Animations |
| `src/adapters/cli/commands/migrate_nas_command.py` | CLI : --include-raw, --fast, --category, --all-categories, sous-barre Rich |
| `tests/unit/services/migration/` | 161 tests TDD (de 73 → 161) |
| `migration/plan.json` (utilisateur) | Plan en cours d'exécution |
| `migration/review/*.csv` | low_rated.csv, unrated.csv, broken.csv, needs_validation.csv, already_in_library.csv |

---

## Resume Instructions

### Si l'apply est terminé côté utilisateur

1. Vérifier l'état post-apply :
   ```bash
   uv run cineorg migrate-nas status ./migration/plan.json
   ls -la /media/NAS/volume5/Films/    # ou wherever storage_dir pointe
   sqlite3 .cineorg/cineorg.db "SELECT COUNT(*) FROM movies WHERE file_path IS NOT NULL"
   ```
2. Inspecter les CSV `already_in_library.csv` et `needs_validation.csv`.
3. Si tout est OK : ouvrir PR `feat/migrate-nas-raw-mode` vers master via `gh pr create --base master`.

### Si l'apply tourne encore

1. Vérifier l'avancement dans le terminal du user (barre Rich).
2. Si le user veut Ctrl+C : safe via state store atomique. Relance via `apply --fast` reprend là où c'était.

### Pour la suite milestone v2.1

3. Une fois la PR mergée, supprimer `migration_nas.py` historique (1211 lignes à la racine, déjà en untracked, jamais committé).
4. `/paul:plan` pour phase 41 Jellyfin — clôt v2.1.

---

## Bottleneck identifié (NAS Synology)

Le NAS bride à ~40 MB/s en écriture (volume5 NFS sur 192.168.1.11). Tests confirmés :
- Réseau gigabit Full Duplex côté station ✓
- Mount NFS optimisé (async, rsize=1M) ne change rien
- Lecture brute disque source : 14 GB/s (cache OS)
- Écriture NAS : 39-42 MB/s peu importe les options

C'est un bottleneck physique (CPU NAS, type disque, RAID, encryption volume DSM). Aucune piste software ne peut faire mieux. Pour les futures migrations massives, recommander à l'utilisateur :
- Désactiver l'antivirus DSM pendant la migration
- Pause sur l'indexation Media Server
- Si possible, ajouter un cache SSD au NAS

---

## Decisions à logger dans STATE.md

À ajouter dans la section Decisions de STATE.md (au prochain `/paul:resume` ou manuel) :

- Migration NAS — Bucket ALREADY_IN_LIBRARY : skip œuvres déjà en DB CineOrg avec file_path (économie transfert + détection doublons)
- Migration NAS — flag `--fast` (verify_hash=False) : skip xxh3_64 source+dest, reprise basée sur taille (gain ~50 % temps total sur disques lents)
- Migration NAS — filtrage catégories scanner : préfixes ("film", "seri", "anim") insensibles casse/accents, opt-out via `--all-categories`
- Migration NAS — bwlimit défaut (0, 50, 25, 10, 5) MB/s : 1er essai sans limite, retry dégressif uniquement si erreur réseau
- Migration NAS — parser progress2 supporte locale fr (séparateur `.` ou `,` dans les nombres)
- Migration NAS — bottleneck identifié : NAS Synology saturé à ~40 MB/s en écriture (hardware, pas software)
- Migration NAS — routage film/série : `parsed.media_type` autoritaire (path heuristique testée, rejetée car régression sur films d'animation rangés en Animations/)

---

*Handoff créé : 2026-05-10 (session après-midi).*
*Session : mode raw 100 % livré (étapes 1-5 + améliorations matcher + UX apply), apply prod en cours sur /media/wd10-1, 25 commits sur feat/migrate-nas-raw-mode.*
