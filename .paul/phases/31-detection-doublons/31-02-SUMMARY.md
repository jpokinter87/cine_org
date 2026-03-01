---
phase: 31-detection-doublons
plan: 02
subsystem: ui
tags: [fastapi, jinja2, htmx, duplicates, quality]

requires:
  - phase: 31 plan 01
    provides: CLI check-duplicates avec _build_media_info, _format_*, _load_whitelist, calculate_quality_score
provides:
  - Page web /duplicates avec affichage des doublons, comparaison qualité et gestion whitelist
  - Suppression de doublons vers la corbeille avec distinction doublon DB vs fichiers distincts
  - Boutons visionner et réassocier par copie
affects: [maintenance (corbeille), quality dashboard (lien)]

tech-stack:
  added: []
  patterns: [HTMX partial swap pour whitelist, dialogue confirmation custom pour suppression]

key-files:
  created:
    - src/web/routes/duplicates.py
    - src/web/templates/duplicates/index.html
    - src/web/templates/duplicates/_results.html
  modified:
    - src/web/app.py
    - src/web/static/css/style.css
    - src/web/templates/quality/dashboard.html
    - src/web/templates/base.html

key-decisions:
  - "overflow:hidden retiré de .dup-group (même cause que .lib-season-group — popover tronqué)"
  - "Distinction doublon DB (même file_path) vs fichiers physiques distincts"
  - "Bouton Ignorer au lieu d'Accepter (plus explicite)"
  - "Score vert pour meilleure version, pas de badge quand scores égaux"
  - "Popover lecteur : vérification débordement horizontal ajoutée globalement"

patterns-established:
  - "Détection doublons DB via COUNT(*) sur même file_path"
  - "Suppression conditionnelle : ne pas toucher symlink/VideoFile si d'autres MovieModel partagent le même file_path"

duration: ~90min
completed: 2026-03-01T19:40:00Z
---

# Phase 31 Plan 02: Vue web doublons — Summary

**Page /duplicates avec affichage des doublons par groupe, comparaison qualité, gestion whitelist, visionner, réassocier et suppression vers corbeille.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90min |
| Completed | 2026-03-01 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 6 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Page doublons accessible | Pass | GET /duplicates retourne 200 avec groupes |
| AC-2: Comparaison visuelle de qualité | Pass | Table par groupe avec résolution, codec, langues, taille, score. Score vert pour le meilleur |
| AC-3: Gestion whitelist depuis le web | Pass | Ignorer/Retirer via HTMX avec swap partiel |
| AC-4: Section whitelistés séparée | Pass | Section collapsible "N doublons ignorés" |

## Accomplishments

- Page /duplicates fonctionnelle avec poster TMDB, titre lié à la fiche, métadonnées techniques comparées
- Gestion whitelist HTMX (ignorer/retirer) avec refresh partiel sans rechargement de page
- Bouton Visionner par copie (réutilise le partial _play_btn.html) pour comparer visuellement
- Bouton Réassocier par copie (ouvre l'overlay TMDB existant) pour corriger les faux doublons
- Suppression vers corbeille avec dialogue de confirmation custom et distinction automatique doublon DB vs fichiers distincts
- Badge "doublon DB" affiché quand les copies pointent sur le même fichier physique
- Lien "Doublons" ajouté dans la sidebar de la page Qualité

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/duplicates.py` | Created | Routes GET /, POST whitelist-add/remove, POST delete |
| `src/web/templates/duplicates/index.html` | Created | Page principale doublons |
| `src/web/templates/duplicates/_results.html` | Created | Partial HTMX (stats + groupes + whitelist + dialogue suppression) |
| `src/web/app.py` | Modified | Import et montage du router duplicates |
| `src/web/static/css/style.css` | Modified | ~250 lignes de styles dup-* + popover-right + qdash-card-icon-dup |
| `src/web/templates/quality/dashboard.html` | Modified | Carte "Doublons" dans sidebar qualité |
| `src/web/templates/base.html` | Modified | Fix popover débordement horizontal (popover-right) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| "Ignorer" au lieu d'"Accepter" | Plus explicite — l'utilisateur comprend l'action | UX plus claire |
| Suppression ajoutée (hors scope initial) | Demandée par l'utilisateur — indispensable pour gérer les doublons | Route POST /duplicates/delete avec corbeille |
| Distinction doublon DB vs fichiers distincts | 3 groupes avaient le même file_path (entrées DB en double) | Badge "doublon DB", suppression DB-only sans toucher symlink |
| Pas de badge "Conserver" quand scores égaux | Confus quand les deux copies sont identiques | Score vert suffit pour identifier le meilleur |
| Fix popover horizontal global | Le popover lecteur débordait à droite dans la table étroite | Classe CSS popover-right ajoutée dans base.html pour tous les popovers |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 3 | Fonctionnalités demandées par l'utilisateur |
| Auto-fixed | 2 | Bugs UX corrigés pendant le test |

**Total impact:** Ajouts essentiels demandés par l'utilisateur, pas de scope creep.

### Scope Additions

1. **Bouton Visionner par copie** — demandé pour pouvoir comparer visuellement les fichiers
2. **Bouton Réassocier par copie** — demandé pour corriger les faux doublons (ex: End of Watch)
3. **Suppression vers corbeille** — demandé pour éliminer les copies indésirables

### Auto-fixed Issues

1. **Popover tronqué par overflow:hidden** — `.dup-group` avait `overflow:hidden`, retiré (même pattern que `.lib-season-group`)
2. **Popover débordant à droite** — Ajout vérification `rect.right > window.innerWidth` + classe `popover-right` dans base.html (fix global)

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ✓ | Chargé avant création des templates |

## Next Phase Readiness

**Ready:**
- Phase 31 complète (CLI + web doublons)
- Prêt pour Phase 32 (NFO & Artwork Sidecar Jellyfin)

**Concerns:**
- Page maintenance sans gestion corbeille (deferred issue)
- 3 doublons DB à purger manuellement (deferred issue)

**Blockers:** None

---
*Phase: 31-detection-doublons, Plan: 02*
*Completed: 2026-03-01*
