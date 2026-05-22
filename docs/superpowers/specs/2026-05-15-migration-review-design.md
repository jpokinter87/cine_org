# Spec — Évolution de la migration NAS : cycle de review interactif

**Date** : 2026-05-15
**Statut** : Validé via brainstorming, prêt pour writing-plans
**Branche cible** : `feat/migrate-nas-review` (à créer)
**Phase suggérée** : 44 (Migration NAS — Review interactive)

---

## 1. Contexte

### Constat actuel

La fonction `migrate-nas` (CineOrg) suit un pipeline binaire :

```
plan → produit plan.json + CSVs (5 buckets)
apply → transfère uniquement le bucket MIGRATE
```

Tout ce qui n'est pas un match propre (bucket MIGRATE) tombe dans des CSV inertes
(`needs_validation.csv`, `unrated.csv`, `low_rated.csv`, `already_in_library.csv`,
`broken.csv`) sans cycle de retour. L'utilisateur doit ouvrir LibreOffice et n'a
aucune action possible derrière.

Run de référence (wd10-1, 2026-05-15) :

| Bucket | Items | Action requise |
|---|---|---|
| MIGRATE | 12 | ✅ Transférés via `apply` |
| **NEEDS_VALIDATION** | **117** | Match TMDB ambigu — choisir parmi top candidates ou rechercher |
| UNRATED | 17 | Note absente — décider migrer ou skip |
| ALREADY_IN_LIBRARY | 11 | Doublons potentiels — comparer qualité, décider |
| LOW_RATED | 6 | Note < seuil 6.0 — décider migrer quand même |

Soit **140 items à arbitrer + 11 doublons** sans interface dédiée. Le user doit
faire des allers-retours manuels entre CSV, console et `validate manual`.

### Vision

Refermer la boucle : transformer les buckets non-MIGRATE en queue de décisions
exploitable, en CLI prioritaire (workflow batch fluide, cohérent avec
`validate_commands` existants) et web optionnel (escalade pour items litigieux
nécessitant comparaison visuelle).

---

## 2. Décisions architecturales

| # | Décision | Justification |
|---|---|---|
| 1 | Hybride CLI + Web, **CLI prioritaire** | Le workflow par défaut est CLI ; web optionnel pour items deferred via action `[w]`. Cohérent avec process/validate existants. |
| 2 | **Les 4 buckets** non-MIGRATE en review unifiée | needs_validation (majoritaire), unrated, low_rated, already_in_library. Sous-flow par bucket avec actions adaptées. |
| 3 | **Décisions découplées** du plan | plan.json reste artefact immuable (audit). Décisions persistées dans state_store SQLite (déjà colocalisé, déjà reprenable). `apply` joint les deux. |
| 4 | Palette d'actions complète incl. **TMDB live search** | `[a]ccept top`, `[1-5] pick`, `[s]earch`, `[r]eject`, `[k]eep skip`, `[w]eb`, `[q]uit`. Réutilise `tmdb_client` + `MatcherService`. |
| 5 | already_in_library : **DuplicateDetector existant** | Auto-comparaison qualité (résolution + codec + bitrate) → recommandation. User valide en 1 keystroke. |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  migrate-nas plan          (existant — inchangé)            │
│    → produit plan.json + CSVs                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  migrate-nas review <plan>      (NOUVEAU)                   │
│    Loop CLI Rich, item-par-item, 4 buckets unifiés          │
│    Actions : accept/pick/search/reject/skip/web/quit        │
│    Réutilise : tmdb_client + MatcherService + DuplicateDet. │
│              candidate_display + interactive_loop patterns  │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│  state_store SQLite      │    │  /migration/<plan>/review    │
│  (étendu)                │    │  page web (NOUVEAU)          │
│  + table migration_      │◄──►│  Liste items deferred-to-web │
│    decisions             │    │  Réutilise overlay reassoc.  │
└──────────────────────────┘    └──────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  migrate-nas apply <plan>      (étendu)                     │
│    Lit plan + decisions, transfère MIGRATE + approuvés      │
│    Logique transfer_executor inchangée                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Composants

### 4.1 `MigrationReviewService` (nouveau)

Service métier orchestrateur. Sous `src/services/migration/review_service.py`.

```python
class MigrationReviewService:
    def __init__(
        self,
        *,
        plan: MigrationPlan,
        state_store: MigrationStateStore,  # étendu, cf. 4.2
        tmdb_client: TMDBClient,
        tvdb_client: TVDBClient,
        matcher: MatcherService,
        duplicate_detector: DuplicateDetector,
    ): ...

    def iter_pending(
        self, *, bucket: Optional[Bucket] = None, resume: bool = True
    ) -> Iterator[MigrationItem]:
        """Yield les items sans décision (ou tous si resume=False)."""

    def decide(
        self, item_id: str, decision: Decision
    ) -> None:
        """Persiste une décision dans state_store. Idempotent."""

    async def search_tmdb(
        self, query: str, *, is_series: bool, year: Optional[int] = None
    ) -> list[ScoredCandidate]:
        """Recherche TMDB live + scoring via MatcherService."""

    def duplicate_recommendation(
        self, item: MigrationItem
    ) -> DuplicateRecommendation:
        """Pour already_in_library : score qualité source vs dest, retourne reco."""
```

### 4.2 Extension `MigrationStateStore`

Nouvelle table dans le SQLite existant :

```sql
CREATE TABLE IF NOT EXISTS migration_decisions (
    item_id TEXT PRIMARY KEY,
    bucket_origin TEXT NOT NULL,
    decision TEXT NOT NULL,             -- approved | rejected | skipped | deferred_to_web
    chosen_tmdb_id INTEGER,
    chosen_tvdb_id INTEGER,
    chosen_title TEXT,
    chosen_year INTEGER,
    chosen_score REAL,
    duplicate_action TEXT,              -- pour already_in_library : keep_dest|replace|delete_source
    delete_source_after BOOL DEFAULT 0,
    reason TEXT,
    decided_at TEXT NOT NULL,
    decided_via TEXT NOT NULL           -- cli | web
);
```

État `pending` = absent de la table. Idempotent : ré-décider over-write.

Méthodes ajoutées sur `MigrationStateStore` :
- `save_decision(decision: Decision) -> None`
- `load_decisions() -> dict[str, Decision]`
- `get_decision(item_id: str) -> Optional[Decision]`
- `decision_summary() -> dict[str, int]`

### 4.3 CLI `migrate-nas review`

Nouveau module `src/adapters/cli/commands/migrate_nas_command/review.py` (intégré
au sous-package livré en B#5) :

```python
@migrate_nas_app.command("review")
def review_command(
    plan_path: Annotated[Path, typer.Argument(...)],
    bucket: Annotated[Optional[Bucket], typer.Option("--bucket")] = None,
    resume: Annotated[bool, typer.Option("--resume/--restart")] = True,
    state_store: Annotated[Optional[Path], typer.Option("--state-store")] = None,
):
    """Review interactive des items en attente (4 buckets unifiés)."""
```

Loop CLI :

```
┌─ [42/140] needs_validation • Films ─────────────────────────┐
│ Source : /media/wd10-1/.../Wrong.mkv  (1.5 GB)              │
│ Parsed : title="Wrong" year=None                            │
│                                                              │
│ Top candidates TMDB :                                        │
│   1. Wrong                              (2012) score 67  ●  │
│   2. Détour mortel [Wrong Turn]         (2003) score 45     │
│   ...                                                        │
└──────────────────────────────────────────────────────────────┘
[a]ccept top  [1-5] pick  [s]earch  [r]eject  [k]eep skip  [w]eb  [q]uit
> _
```

Actions par bucket :

| Bucket | Actions |
|---|---|
| **needs_validation** | a / 1-5 / s / r / k / w / q |
| **unrated** | m (migrate-anyway) / s / k / w / q |
| **low_rated** | m / d (delete-source-after) / k / w / q |
| **already_in_library** | a (accept reco) / k (keep dest) / r (replace dest) / d (delete source) / w / q |

Fin de pass : récap + URL web si items deferred.

### 4.4 Web `/migration/<plan>/review`

Nouveau module `src/web/routes/migration/review.py`.

Routes :
- `GET /migration/review?plan=<path>` — page liste avec filtres (bucket, statut décision, tri)
- `GET /migration/review/<item_id>` — overlay HTMX détail (poster, candidats avec posters)
- `POST /migration/review/<item_id>/decide` — soumission décision
- `GET /migration/review/<item_id>/search?q=<text>` — search TMDB live (HTMX)

Templates dans `src/web/templates/migration/` :
- `review_list.html` (page principale)
- `_review_card.html` (ligne de la liste)
- `_review_detail.html` (overlay détail — réemploie patterns reassociate)
- `_duplicate_compare.html` (variante pour already_in_library)

### 4.5 Extension `migrate-nas apply`

Modification de `orchestrators.run_apply()` :

```python
def run_apply(...):
    plan = deserialize_plan(...)
    store = MigrationStateStore(...)
    decisions = store.load_decisions()  # NOUVEAU

    # Hydrate les items approuvés avec le match retenu
    enhanced_items = []
    for item in plan.items:
        if item.bucket == Bucket.MIGRATE:
            enhanced_items.append(item)
            continue
        decision = decisions.get(item.item_id)
        if decision is None or decision.decision != "approved":
            continue
        # Override match info from decision
        item.match.tmdb_id = decision.chosen_tmdb_id
        item.match.tvdb_id = decision.chosen_tvdb_id
        item.bucket = Bucket.MIGRATE  # enable transfer
        enhanced_items.append(item)
    plan.items = enhanced_items

    # Reste du code apply inchangé
    ...
```

`raw_finalizer` n'a pas besoin d'évoluer : il consomme `item.match` comme avant.

---

## 5. Data flow — exemple end-to-end

```
1. user lance : migrate-nas review migration/wd10-1/plan.json
2. ReviewService charge plan + load_decisions (vide au 1er run)
3. iter_pending() yield 140 items (needs_validation + unrated + low_rated + already_in_library)
4. CLI affiche carte item 1, attend keystroke
5. user tape 'a' → save_decision(item_id, Decision(approved, top match))
6. CLI affiche carte item 2, etc.
7. user fait 50 items, tape 'q' → exit, message "50/140 traités, --resume pour continuer"
8. user revient le lendemain, lance avec --resume
9. iter_pending(resume=True) skippe les 50 décidés, yield les 90 restants
10. user finit, 9 items deferred-to-web
11. CLI affiche : "9 items à arbitrer sur http://192.168.1.15:8000/migration/review?plan=..."
12. user ouvre web, traite les 9 (overlay HTMX, poster, search live)
13. user lance : migrate-nas apply migration/wd10-1/plan.json
14. apply joint plan + decisions, hydrate match, transfère 92 items approved
15. raw_finalizer crée DB entries + symlinks comme pour MIGRATE classique
```

---

## 6. Edge cases

### 6.1 Multi-parts (collision_tmdb tag)

Items La Flor parties 1-4 (tag `collision_tmdb:423778`).

CLI : 1er item du groupe affiche bandeau `🔗 Détecté multi-parts (4 items, tag collision_tmdb:423778)`.
Action `[a]` propose : `Accepter pour les 4 ? [Y/n] Suffix auto = 'Part {N}'`.
Si oui, écrit 4 décisions d'un coup avec titres `La Flor - Part 1`, `Part 2`, etc.

### 6.2 Multi-disk

`migration/wd10-1/plan.json`, `migration/wd10-2/plan.json` etc. Chacun a son
state_store SQLite colocalisé. Décisions isolées par chemin. Pas de logique
cross-plan dans MVP.

### 6.3 Search TMDB live

Action `[s]` : prompt `Nouveau titre ? > ` → `tmdb_client.search(text)` async via
`asyncio.run()` + `MatcherService.score_results()` → ré-affiche carte avec
nouveaux candidats. Touche `b` pour revenir aux candidats originaux.

### 6.4 Re-générer plan.json après review

Cas : user relance `migrate-nas plan` et écrase `plan.json`. Les `item_id`
(hash xxh3_64 du symlink path) restent stables tant que les chemins source
sont identiques → décisions toujours valides. Pas de logique de migration
schema requise.

Si chemin source change (rare, ex: re-mount différent) → décisions perdues
pour ces items, mais préservées pour les autres.

### 6.5 Apply pendant review en cours

Workflow découplé permet `apply` même sur review partielle. Items approved =
transférés. Items pending/skipped/rejected/deferred = ignorés. User peut
reprendre review après et relancer apply.

---

## 7. Réutilisation (zéro duplication)

| Existant | Réemploi |
|---|---|
| `tmdb_client` / `tvdb_client` / `api/cache` | search/get_details |
| `MatcherService.score_results` | scoring TMDB |
| `DuplicateDetector` (services/duplicate_detector.py) | already_in_library reco |
| `candidate_display.py` (validation) | format candidats CLI |
| `interactive_loop.py` pattern | structure de loop interactif |
| `_reassociate_overlay.html` | base overlay web |
| `_reassociate_results.html` | liste candidats avec posters |
| `validation_service.search_by_external_id` | search par ID externe |
| `MigrationStateStore` SQLite | étendu (nouvelle table), pas réécrit |
| `MigrationRawFinalizer` | inchangé, consomme `item.match` hydraté |
| `MigrationTransferExecutor` | inchangé |

---

## 8. Plan d'implémentation phasé

### MVP utile (44.1 → 44.6)

| Phase | Livrable | Test |
|---|---|---|
| **44.1** | `migration_decisions` table + `MigrationReviewService` (decide/load/iter_pending) | Unit tests sur le service |
| **44.2** | `migrate-nas review` CLI loop (cas needs_validation seul) + actions a/N/r/k/q | TDD sur la loop avec stdin mock |
| **44.3** | Action `[s]earch` TMDB live | Unit test avec respx mock |
| **44.4** | Buckets unrated, low_rated, already_in_library + DuplicateDetector | Tests par bucket |
| **44.5** | Action `[w]eb` defer + summary fin de pass + URL | Snapshot tests output Rich |
| **44.6** | `apply` lit decisions, hydrate match raw, transfère | Test e2e plan→review→apply |

### Polish (44.7 → 44.9)

| Phase | Livrable | Test |
|---|---|---|
| **44.7** | Page web liste `/migration/review` + overlay détail (réemploi reassociate) | Tests routes + templates |
| **44.8** | Multi-parts auto-handle (tag collision_tmdb) | Test cas La Flor |
| **44.9** | Doc README + exemple session complète | Manuel |

---

## 9. Tests stratégie

- **TDD sur ReviewService** : decisions persistées correctement, iter_pending filtre, search TMDB mocké via `respx`.
- **TDD sur CLI loop** : injection stdin mocké, vérif actions persistées + display Rich (snapshot via `rich.console.capture`).
- **Test e2e MVP** : génère un plan synthétique avec 1 item par bucket, lance review en mode scripté, lance apply, vérifie transferts.
- **Tests web** : routes retournent bons fragments HTMX, decisions persistées via POST.

---

## 10. Risques & mitigations

| Risque | Mitigation |
|---|---|
| Action `[d]elete-source-after` (low_rated) — perte de données | **Suppression UNIQUEMENT post-commit transfert réussi** (couplée au flag `delete_source_after` dans la décision). Si transfert échoue, source intacte. Confirmation explicite à la décision + log loud + mention README. |
| Action `[r]eplace dest` (already_in_library) — écrasement biblio | Désactiver garde-fou `FileExistsError` uniquement avec ce flag, log loud, audit dans state_store |
| TMDB rate limit pendant search live massif | Utiliser cache existant, throttling par défaut sur search |
| Décisions perdues si `migration/` supprimé | state_store SQLite est dans `migration/<plan>.state.sqlite` — backup recommandé |
| User abandonne au milieu de 117 items | `--resume` natif via state_store, sessions de 30 min suffisent |

---

## 11. Out of scope (futurs PR)

- Multi-disk batch processing (review N plans en série) → workflow shell suffit
- Annulation d'une décision déjà commitée (transfert effectué) → restauration manuelle
- Statistiques de session (temps moyen par item, etc.) → hors valeur MVP
- Sync décisions web ↔ CLI en live (websocket) → CLI prioritaire = pas critique
- Export décisions vers format autre (CSV, etc.) → pas demandé
