# Plan — corrections de l'audit UI Impeccable

Spec : `docs/superpowers/specs/2026-10-25-audit-ui-impeccable-design.md`

1. Couleur (`style.css` `:root` + occurrences en dur, templates à `style=` coloré)
   → vérifier : détecteur `low-contrast` sur les 12 pages.
2. Typographie (tailles < 0.6875rem, synopsis, titres)
   → vérifier : détecteur `undersized-ui-text`, `line-length`.
3. Robustesse a11y (templates config, transfert, bibliothèque, workflow ; `static/js/dialogs.js`)
   → vérifier : tests web + navigation clavier Playwright (Tab/Entrée/Échap).
4. Mouvement (bloc `prefers-reduced-motion`)
   → vérifier : capture Playwright avec `reduced_motion="reduce"`.
5. Optimisation (`transition: all`)
   → vérifier : `grep` vide.
6. Finition (side-tab, carte imbriquée)
   → vérifier : détecteur.
7. README (section Interface web : accessibilité / mouvement réduit), bump commitizen, PR.

Risques : régression visuelle d'un sélecteur CSS partagé (atténué par captures avant/après
des pages clés) ; JS inline qui cible `legend`/`div` (vérifier chaque handler converti).
