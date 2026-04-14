---
phase: 40-lecteur-dunehd
plan: 02
subsystem: ui
tags: [dunehd, config, htmx, jinja2, forms, validation, player-profiles]

requires:
  - phase: 40-01
    provides: schéma profil étendu (type/ip/smb_*) + backend DuneHDPlayer + dispatcher
provides:
  - UI config profils avec sélecteur type (mpv/dunehd) et champs conditionnels
  - validation backend _validate_profile_form() (IPv4, préfixes smb://, remote SSH)
  - badge de type (MPV/DUNEHD) sur les cartes profil + affichage adapté des détails
  - bandeau d'erreur dans le fragment quand la validation échoue
  - 10 tests unitaires FastAPI TestClient couvrant les routes add/edit
affects: [41 (Jellyfin) — patterns UI config réutilisables, futurs backends (Chromecast, Plex Remote)]

tech-stack:
  added: []
  patterns:
    - Champs conditionnels Jinja2 toggled via JS (closure sur form courant)
    - Validation backend retournant (profile, error) avec fragment HTMX + bandeau
    - FastAPI TestClient + isolation _PROFILES_FILE via monkeypatch pour tests routes

key-files:
  created:
    - tests/unit/test_config_routes.py
  modified:
    - src/web/templates/config/player_profiles.html
    - src/web/routes/config.py
    - src/web/static/css/style.css

key-decisions:
  - "Styles ajoutés dans style.css (centralisé) plutôt qu'un nouveau config.css (fichier inexistant dans le projet)"
  - "Validation minimale sur le préfixe SMB (smb:// requis, reste libre) : l'utilisateur peut avoir des shares exotiques"
  - "Regex IPv4 simple (^\\d{1,3}(\\.\\d{1,3}){3}$) suffisante pour un LAN privé, pas de validation stricte RFC"
  - "Bandeau d'erreur in-fragment plutôt que toast/dialog : propagation naturelle via HTMX hx-swap"
  - "Bouton 'Ajouter un profil' restylé (fond ambre, bordure pleine) suite retour UX utilisateur pendant le checkpoint"

patterns-established:
  - "_validate_profile_form() comme entry-point unique de normalisation/validation pour add+edit (pas de duplication)"
  - "Champs hors type courant forcés à None à la persistance (évite les résidus SSH quand on passe mpv→dunehd)"
  - "Test route config via FastAPI minimal (FastAPI() + router seul) sans lifespan Container, isolant les tests de la DB"

duration: ~35min
started: 2026-04-14T16:00:00Z
completed: 2026-04-14T16:35:00Z
---

# Phase 40 Plan 02: UI Config Profils DuneHD — Summary

**Interface web de config profils étendue aux profils DuneHD (sélecteur type, champs conditionnels IP/SMB, validation backend, badges MPV/DUNEHD), lecture end-to-end vérifiée sur Dune physique, 10 tests routes verts + bouton "Ajouter" rendu visible.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~35min |
| Started | 2026-04-14T16:00:00Z |
| Completed | 2026-04-14T16:35:00Z |
| Tasks | 3/3 completed (dont checkpoint human-verify) |
| Files modified | 4 (1 créé, 3 modifiés) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1 Formulaire d'ajout étendu | ✅ Pass | Select type + groupes `.profile-fields-mpv`/`.profile-fields-dunehd`, toggle JS, défaut mpv |
| AC-2 Édition d'un profil DuneHD | ✅ Pass | Pré-remplissage via `profile.type`, toggle dynamique mpv↔dunehd vérifié au checkpoint |
| AC-3 Validation backend | ✅ Pass | 10 tests routes : IP vide/invalide, SMB absent/non-smb://, mpv remote sans SSH → rejet ; cas valides → création |
| AC-4 Affichage cartes profil | ✅ Pass | Badge `profile-type-badge` (MPV slate / DUNEHD ambre), détails adaptés (IP+SMB pour dunehd, command+SSH pour mpv) |
| AC-5 Test end-to-end manuel | ✅ Pass | Checkpoint approuvé : profil DuneSalon créé via UI, film + épisode lancés physiquement sur Dune 192.168.1.4 |

## Accomplishments

- **UI config complète pour DuneHD** : l'utilisateur configure ses profils entièrement via le web (type, IP, préfixes SMB) sans éditer `player_profiles.json` à la main
- **Validation robuste sans régression mpv** : `_validate_profile_form()` unifie la logique add+edit, rejette les saisies incomplètes avec un message explicite, et n'impacte aucun profil mpv existant (rétrocompat vérifiée par les tests + checkpoint)
- **Lecture end-to-end validée sur Dune physique** : profil créé via UI → "Visionner" depuis la bibliothèque → Dune 192.168.1.4 lance effectivement le film et l'épisode (shares SMB JPSERVER Films + Series TV)
- **10 tests routes FastAPI TestClient** : couverture complète des cas de validation (ajout/édition, mpv/dunehd, succès/erreur) en isolation (_PROFILES_FILE monkeypatched par test)
- **Fix UX spontané** : bouton "Ajouter un profil" rendu visible (fond ambre 10%, bordure pleine, hover inversé) après retour utilisateur pendant le checkpoint

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/templates/config/player_profiles.html` | Modified | Sélecteur type + groupes conditionnels mpv/dunehd + JS togglePlayerTypeFields() + badge de type + affichage adapté + bandeau erreur |
| `src/web/routes/config.py` | Modified | Ajout `_validate_profile_form()` + `_IP_REGEX` + refactor des routes add/edit pour utiliser la validation |
| `src/web/static/css/style.css` | Modified | Styles `.profile-type-badge` (mpv/dunehd), `.profile-error-banner`, restyle `.profile-add-toggle` (visibilité renforcée) |
| `tests/unit/test_config_routes.py` | Created | 10 tests FastAPI TestClient : validation dunehd (5), compatibilité mpv (3), édition (2) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Styles dans `style.css` (pas `config.css`) | Plan listait `config.css` mais le fichier n'existe pas ; tous les styles profil sont déjà dans `style.css` | Cohérence CSS centralisée, aucune dette créée |
| Regex IPv4 simple | LAN privé, pas besoin de validation RFC stricte ; les erreurs réseau au runtime remontent via `DuneHDResult` | Validation lisible, maintenance facile |
| Validation SMB minimale (préfixe `smb://` uniquement) | Autorise les shares avec espaces/accents/noms exotiques | Pas de faux positifs bloquants pour des configs légitimes |
| Bandeau in-fragment plutôt que toast | Cohérent avec le pattern HTMX du projet (fragments partiels via hx-swap) | Zéro JS supplémentaire, accessibilité `role="alert"` native |
| Champs hors type courant forcés à None | Évite qu'un profil mpv→dunehd conserve ses anciens ssh_host/user en résidu | État du profil toujours cohérent avec son type |
| Restyle bouton "Ajouter un profil" | Retour utilisateur au checkpoint : bouton trop discret en bordure dashed/gris | Ajout minimal (CSS uniquement), aucun impact sur le reste de l'UI |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minime (fichier CSS de destination ajusté) |
| Scope additions | 1 | UX-driven, très localisé (bouton Ajouter) |
| Deferred | 0 | — |

**Total impact :** Écarts UX-driven cohérents avec le plan. Aucun scope creep.

### Auto-fixed Issues

**1. [Infra] `config.css` listé dans files_modified mais inexistant**
- **Found during:** Task 1 (édition CSS)
- **Issue:** Le plan référençait `src/web/static/css/config.css` qui n'existe pas ; tous les styles profil vivent dans `style.css`
- **Fix:** Styles ajoutés dans `style.css` à proximité des règles profil existantes
- **Files:** `src/web/static/css/style.css`
- **Verification:** Checkpoint visuel approuvé, badges affichés correctement

### Scope additions

**1. [UX] Restyle bouton "Ajouter un profil"**
- **Origine:** Retour utilisateur pendant le checkpoint Task 3 ("j'ai longtemps cherché le bouton, il n'est pas assez visible")
- **Ajout:** Fond `rgba(212, 168, 83, 0.1)` + bordure pleine ambre + texte accent + hover inversé (fond ambre plein)
- **Files:** `src/web/static/css/style.css`
- **Justification:** Demande UX minimaliste, concernée directement par le scope du plan (UI config profils)

### Deferred Items

Aucun.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `uv run ruff check` échoue avec "No such file or directory" (ruff pas dans les deps principales) | Utiliser `uvx ruff check` pour exécuter ruff via uv-tool ad-hoc |
| `uv run pytest` idem (pytest pas auto-installé) | `uv sync --all-extras` puis `uv run python -m pytest` |

## Next Phase Readiness

**Ready :**
- Phase 40 complète côté fonctionnel (backend 40-01 + UI config 40-02), lecture DuneHD utilisable sans édition de fichier JSON
- Patterns UI conditionnels + validation backend disponibles pour Phase 41 (Jellyfin) si besoin d'UI config ajoutée
- Sous-package `src/services/player/` prêt à accueillir d'autres backends (Chromecast, Plex Remote)

**Concerns :**
- Pas de feedback position/état live depuis le Dune (limitation API acceptée, déjà loggée en deferred issue)
- Pas de test automatique end-to-end du Dune (checkpoint manuel uniquement, acceptable pour du matériel physique)
- Idée "en cours de lecture" (reprise de position) explorée en fin de session : non-applicable au Dune sans polling complexe, mais faisable pour mpv local/remote — candidat potentiel Phase 42 après Jellyfin

**Blockers :** None — transition vers Phase 41 (Jellyfin) prête.

---
*Phase: 40-lecteur-dunehd, Plan: 02*
*Completed: 2026-04-14*
