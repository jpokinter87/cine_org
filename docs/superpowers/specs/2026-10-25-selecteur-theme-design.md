# Sélecteur de thème — design

Date : 2026-10-25 · Branche : `feat/theme-selector`

## Contexte

L'audit Impeccable (PR #36) a rapatrié l'interface sur des variables CSS. Une planche de
maquettes (artifact « Thèmes CineOrg ») a proposé quatre directions ; le gestionnaire retient
**Nuit ambrée** (défaut, l'identité actuelle) et trois thèmes optionnels : **Cinémathèque**
(clair éditorial), **Velours** (salle de cinéma Art déco) et **Kodachrome** (pellicule des
années 70). « Régie » est écarté : sa densité impose des changements de mise en page.

## Objectif

Chaque navigateur choisit son thème dans la barre de navigation ; le choix est mémorisé et
appliqué avant le premier affichage. Nuit ambrée reste strictement identique.

## Décisions

1. **Marque ≠ avertissement.** Nouvelle variable `--accent` (+ `--accent-dim`) pour la couleur
   de marque (lien actif, bouton principal, focus, « Surprends-moi », progression…).
   `--accent-amber` garde le rôle d'avertissement (score moyen, doublon, action à confirmer).
   Dans Nuit ambrée, `--accent` = `--accent-amber` : aucun changement visible.
2. **Couleurs translucides tokenisées.** Les `rgba()` dérivés des accents (ambre, émeraude,
   rose, bleu) et du blanc deviennent `color-mix(in srgb, var(--token) N%, transparent)`.
   Équivalent exact dans Nuit ambrée. Le blanc translucide passe par `--tint` (blanc sur les
   thèmes sombres, encre sur Cinémathèque). Les ombres et voiles noirs restent en dur.
3. **Thèmes = blocs `[data-theme="…"]`** posés sur `<html>`, redéfinissant couleurs, polices,
   arrondis et ombres, plus quelques signatures légères issues des maquettes (cadre doré des
   jaquettes et titres en capitales pour Velours, filets sans ombre pour Cinémathèque, formes
   plus rondes pour Kodachrome). Aucune modification de mise en page.
4. **Mémorisation par navigateur** (`localStorage`, clé `cineorg_theme`), comme « Vous
   regardez sur ». Un script inline dans `<head>` pose `data-theme` avant le rendu (pas de
   flash) et ne charge que les polices du thème actif.
5. **Sélecteur** : `<select>` étiqueté « Thème » à côté de « Vous regardez sur », quatre
   entrées. `<meta name="theme-color">` suit le thème (barre d'état du téléphone).

## Hors périmètre

Thème « Régie », mise en page propre à un thème, réglage serveur global, suivi automatique du
mode clair/sombre du système.

## Critères de succès

- Tests web : le sélecteur propose les quatre thèmes ; le script de `<head>` est présent ;
  la feuille de style définit un bloc par thème et `--accent`.
- `style.css` ne contient plus de `rgba()` dérivé des accents ou du blanc.
- Contraste texte ≥ 4,5:1 (texte, secondaire, `--text-muted`, accent sur fond et sur
  `--on-accent`) mesuré pour chaque thème par script.
- Relecture visuelle des quatre thèmes sur le serveur de test (bureau + téléphone).
