# Corrections de l'audit UI Impeccable — design

Date : 2026-10-25 · Branche : `feat/ui-audit-impeccable`

## Contexte

`/impeccable audit` (détecteur sur sources + 12 pages servies, bureau 1280×800 et mobile
412×915) a noté l'interface **12/20** : accessibilité 2, performance 3, thème 2,
responsive 3, cohérence 2. `PRODUCT.md` (racine) fixe le cadre : outil de gestion dense pour
un seul gestionnaire, bibliothèque où le foyer flâne et lance la lecture, aucune contrainte
d'identité imposée.

## Objectif

Corriger les P1/P2 de l'audit **sans refonte** : l'identité en place (nuit bleutée, accent
ambre, Instrument Serif + DM Sans) est conservée et rendue cohérente.

## Périmètre

1. **Couleur** — `--text-muted` ≥ 4,5:1 sur tous les fonds ; badges lisibles (texte foncé sur
   fond vif) ; palette parallèle en dur (`#f59e0b`, `#ef4444`, `#9ca3af`, `#4caf50`,
   `#ff9800`…) rapatriée sur les tokens `--accent-*` ; pastilles néon cyan/violet des fiches
   ramenées dans le système.
2. **Typographie** — aucun texte fonctionnel < 11 px ; synopsis ≤ 70ch ; `text-wrap: balance`
   sur les titres.
3. **Robustesse a11y** — vrais `<button>` (sections config, groupes de l'arbre de transfert,
   zoom jaquettes, infobulles de résultats) ; sémantique de dialogue + focus géré pour les
   fenêtres superposées existantes (helper JS commun, sans réécrire leurs fonctions
   show/hide) ; hiérarchie des titres sans saut ; `aria-expanded` sur le menu mobile.
4. **Mouvement** — bloc `prefers-reduced-motion` : fondus courts à la place des
   translations, boucles de reflet arrêtées, révélation « Surprends-moi » raccourcie.
5. **Optimisation** — `transition: all` remplacés par des propriétés explicites.
6. **Finition** — barres latérales colorées > 1 px remplacées, carte imbriquée de la fiche
   série aplatie.

Hors périmètre : refonte visuelle, thème clair / variantes de thème (préparé par l'étape 1,
à proposer ensuite), découpage du CSS monolithique, unification des points de rupture
(gain faible, risque de régression mobile élevé).

## Critères de succès

- Le détecteur ne remonte plus `low-contrast` sur `--text-muted`, ni `undersized-ui-text`,
  ni `side-tab`, ni `nested-cards`, ni `skipped-heading` sur les pages scannées.
- Les sections repliables, le zoom de jaquette et les groupes de l'arbre sont activables
  au clavier.
- Les tests web existants passent.
- Captures bureau + mobile relues : aucune régression visuelle évidente.
