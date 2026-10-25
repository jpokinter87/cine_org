# Plan — sélecteur de thème

Spec : `docs/superpowers/specs/2026-10-25-selecteur-theme-design.md`

1. Tests (rouges) : sélecteur à 4 options dans la nav, script `<head>`, blocs `[data-theme]`,
   absence de `rgba()` d'accent → vérifier : `pytest tests/unit/web/test_theme_select.py` échoue.
2. `rgba()` d'accents et de blanc → `color-mix()` (script ponctuel, hors dépôt)
   → vérifier : `grep` vide, rendu Nuit ambrée inchangé.
3. `--accent` : tri des usages de `--accent-amber` (marque vs avertissement)
   → vérifier : liste des sélecteurs basculés relue.
4. Blocs de thèmes + signatures + polices → vérifier : script de contraste sur chaque thème.
5. Sélecteur + script `<head>` + `theme-color` → vérifier : tests verts, suite complète.
6. Serveur de test 8011 (base en lecture seule) → relecture par le gestionnaire.
7. README (section Interface web), bump commitizen, PR.

Risques : usage d'ambre mal classé (sans effet sur Nuit ambrée, visible dans les autres
thèmes) ; texte blanc en dur sur un fond devenu clair dans Cinémathèque (à repérer en relecture).
