---
phase: 04-transfert-conflits
plan: 01
subsystem: ui
tags: [fastapi, htmx, sse, jinja2, transfer, conflict-resolution, dry-run]

requires:
  - phase: 03-orchestration-workflow
    provides: SSE progress pattern (WorkflowProgress + EventSource), cascade auto-validation
provides:
  - Page /transfer avec arborescence batch des transferts prévus
  - Exécution transfert avec progression SSE temps réel
  - Résolution interactive des conflits (DUPLICATE auto-skip, NAME_COLLISION/SIMILAR_CONTENT dialogue)
  - Mode dry-run (simulation sans modification du filesystem)
  - Résultats détaillés (noms formatés, chemins storage + symlink)
affects: [05-bibliotheque-maintenance]

tech-stack:
  added: []
  patterns:
    - TransferProgress shared state avec asyncio.Event pour pause/resume conflit
    - Silent Rich console pour neutraliser les print de batch_builder en contexte web
    - _record_transfer() helper pour centraliser le tracking des détails

key-files:
  created:
    - src/web/routes/transfer.py
    - src/web/templates/transfer/index.html
    - src/web/templates/transfer/_batch_tree.html
    - src/web/templates/transfer/_progress.html
  modified:
    - src/web/app.py
    - src/web/templates/base.html
    - src/web/static/css/style.css

key-decisions:
  - "Réutiliser build_transfers_batch tel quel avec silent Rich console (StringIO) au lieu de refactorer"
  - "Conflit dialog construit en JS dynamique (pas de template séparé _conflict.html)"
  - "Résultats (tooltips + détails) intégrés dans _progress.html au lieu d'un _results.html séparé"
  - "Mode dry-run ajouté pour permettre la simulation sans risque"
  - "display_name (nom formaté) utilisé dans les résultats au lieu du nom source"

patterns-established:
  - "TransferProgress.dry_run pour basculer entre simulation et exécution réelle"
  - "transferred_details list[dict] pour résultats enrichis (name, storage, symlink)"
  - "_group_by_path() pour organiser les transferts en arborescence par répertoire parent"

duration: ~90min
started: 2026-02-23T15:00:00Z
completed: 2026-02-23T16:40:00Z
---

# Phase 4 Plan 01: Transfert & Conflits Summary

**Page /transfer complète avec arborescence batch, transfert SSE, résolution de conflits interactive et mode simulation dry-run**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90 min |
| Started | 2026-02-23 15:00 |
| Completed | 2026-02-23 16:40 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files created | 4 |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Page transfert avec résumé batch | Pass | Arborescence Films/Séries avec icônes fichier, taille, destination |
| AC-2: Page transfert vide | Pass | Message explicatif + liens workflow/validation |
| AC-3: Exécution transfert avec progression SSE | Pass | Barre de progression, compteur N/total, nom de fichier en cours |
| AC-4: Détection DUPLICATE | Pass | Auto-skip avec compteur doublons dans résultats |
| AC-5: Détection NAME_COLLISION/SIMILAR_CONTENT | Pass | Dialogue comparatif avec 4 options (keep_old/new/both/skip) |
| AC-6: Résultats finaux | Pass | Compteurs + tableau détaillé par fichier (nom formaté, storage, symlink) |

## Accomplishments

- Route transfert complète : GET /, POST /start, GET /progress (SSE), POST /resolve-conflict
- Arborescence visuelle avec icônes dossier/fichier, groupement par répertoire parent
- Mode dry-run permettant de simuler l'intégralité du transfert sans toucher au filesystem
- Résultats détaillés montrant le nom formaté, le chemin storage relatif et le chemin symlink relatif
- Résolution interactive des conflits avec tableau comparatif technique (taille, résolution, codecs)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/transfer.py` | Created | Routes transfert, TransferProgress, _run_web_transfer, _build_tree_data |
| `src/web/templates/transfer/index.html` | Created | Page principale (vide ou batch tree + boutons simuler/transférer) |
| `src/web/templates/transfer/_batch_tree.html` | Created | Arborescence Films/Séries avec groupes dossier et feuilles fichier |
| `src/web/templates/transfer/_progress.html` | Created | Progression SSE + dialogue conflit JS + résultats détaillés |
| `src/web/app.py` | Modified | Ajout include_router(transfer_router) |
| `src/web/templates/base.html` | Modified | Ajout lien navigation "Transfert" |
| `src/web/static/css/style.css` | Modified | +350 lignes : tree, conflict overlay, transfer details table |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Silent Rich console au lieu de refactorer batch_builder | Minimise les changements dans le code CLI existant | Couplage temporaire acceptable |
| Dialogue conflit en JS dynamique (pas template séparé) | Simplifie l'architecture, le conflit est construit par l'event SSE | Pas de _conflict.html ni _results.html séparés |
| Mode dry-run via query param ?dry_run=1 | Permet de tester le transfert sans risque sur données réelles | Très utile pour UAT |
| display_name = new_filename (nom formaté) | L'utilisateur veut voir le nom final, pas le nom source | Corrige le bug des noms originaux dans les résultats |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 4 | Corrections essentielles |
| Scope additions | 1 | Mode dry-run (demande utilisateur) |
| Deferred | 0 | - |

**Total impact:** Corrections essentielles + ajout dry-run demandé par l'utilisateur pendant l'UAT

### Auto-fixed Issues

**1. Jinja2 `group.items` collision avec dict.items()**
- **Found during:** Task 2
- **Issue:** `group.items` interprété comme la méthode built-in du dict
- **Fix:** Renommé la clé `items` en `files` dans _group_by_path() et tous les templates
- **Verification:** Template rendu correctement

**2. container.config() retourne Settings, pas dict**
- **Found during:** Task 1
- **Issue:** `config["paths"]["storage"]` échoue — Settings est un objet Pydantic
- **Fix:** `settings = container.config()` puis `settings.storage_dir`
- **Verification:** Routes fonctionnelles

**3. TransfererService nécessite storage_dir/video_dir au constructeur**
- **Found during:** UAT
- **Issue:** `container.transferer_service()` sans arguments → TypeError
- **Fix:** Passer `storage_dir=settings.storage_dir, video_dir=settings.video_dir`
- **Verification:** Simulation fonctionne sans erreur

**4. Noms source affichés au lieu des noms formatés dans les résultats**
- **Found during:** UAT
- **Issue:** `filename = source.name` utilisé partout au lieu du nom renommé
- **Fix:** Introduit `display_name = transfer["new_filename"]` pour les résultats
- **Verification:** Tooltip et détails affichent les noms formatés

### Scope Addition

**Mode dry-run (simulation)**
- **Requested by:** Utilisateur pendant UAT
- **Reason:** Éviter de polluer le storage et les symlinks existants pendant les tests
- **Implementation:** Paramètre `?dry_run=1`, bouton "Simuler le transfert", badge DRY RUN
- **Files:** transfer.py, index.html, _progress.html, style.css

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ✓ | Invoqué avant la création des templates et CSS |

Skill audit: All required skills invoked ✓

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Fichiers non visibles dans l'arborescence (seuls les dossiers apparaissaient) | Amélioré le CSS et ajouté des icônes SVG fichier pour distinguer visuellement fichiers et dossiers |
| Compteur SSE bloqué à 8/10 | Ajouté un dernier event `progress` avec le total final juste avant l'event `complete` |
| Templates séparés _conflict.html et _results.html non créés | Intégrés directement dans _progress.html (JS dynamique) — plus simple et fonctionnel |

## Next Phase Readiness

**Ready:**
- Pipeline complet : workflow → validation → transfert fonctionne de bout en bout via l'interface web
- Pattern SSE réutilisable (3e implémentation, bien rodé)
- Mode dry-run pour tester en sécurité

**Concerns:**
- Le silent Rich console est un hack — un refactoring de batch_builder pour séparer données et affichage serait plus propre
- Code dupliqué matching entre workflow web et CLI (hérité de Phase 3)

**Blockers:**
- None

---
*Phase: 04-transfert-conflits, Plan: 01*
*Completed: 2026-02-23*
