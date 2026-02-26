---
phase: 19-config-accordeon
plan: 01
type: summary
---

# Summary: Config Accordéon

## What Was Built

Page /config restructurée avec des sections pliables (accordéon) et version dynamique dans le footer.

### Task 1: Sections en accordéon
- Template `index.html` : chaque `<fieldset>` reçoit une classe `config-section-collapsed` (sauf la première), un chevron SVG dans le `<legend>`, et un wrapper `config-section-body` pour le contenu
- CSS : animation `max-height` + `opacity` pour l'ouverture/fermeture fluide, rotation du chevron à -90° quand fermé, curseur pointer et hover ambre sur les légendes
- JS minimal : `toggleConfigSection(legend)` toggle la classe `config-section-collapsed`
- Section Lecteur (hors formulaire) suit le même pattern
- Les inputs restent dans le DOM (overflow hidden, pas display:none) → le POST envoie toutes les valeurs
- Fix spacing : `.config-page` en flex column avec gap uniforme pour aligner la section Lecteur

### Task 2: Version dynamique footer
- `deps.py` : lecture de `pyproject.toml` via `tomllib` au chargement du module, exposé comme `templates.env.globals["app_version"]`
- `base.html` : `CineOrg v1.4` hardcodé remplacé par `{{ app_version }}`
- `pyproject.toml` : version mise à jour à `1.5.0`

## Acceptance Criteria

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Sections pliables (première ouverte, autres fermées) | ✅ |
| AC-2 | Toggle au clic avec animation fluide | ✅ |
| AC-3 | Contenu préservé, formulaire envoie toutes les valeurs | ✅ |
| AC-4 | Section Lecteur intégrée dans l'accordéon | ✅ |
| AC-5 | Version dynamique dans le footer | ✅ |

## Deviations

- Version lue dans `deps.py` plutôt que `app.py` (plus cohérent car les templates y sont centralisés)
- Fix spacing `.config-page` flex column ajouté après checkpoint (section Lecteur mal alignée)

## Verification

- 890 tests passent (aucune régression)
- Vérification visuelle approuvée par l'utilisateur
- `templates.env.globals["app_version"]` retourne `CineOrg v1.5.0`

## Files Modified

- `src/web/templates/config/index.html` — accordéon (classes, chevrons, section-body)
- `src/web/static/css/style.css` — styles accordion + fix layout page
- `src/web/deps.py` — version dynamique Jinja2 global
- `src/web/templates/base.html` — `{{ app_version }}` remplace le hardcode
- `pyproject.toml` — version 1.5.0
