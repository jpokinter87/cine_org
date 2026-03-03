# Phase 34 — Détection Doublons au Transfert

## Origine

Bug observé : `TV/G-H/Ga-Ha/Gomorra/Gomorra (2014)/Saison 02` — le répertoire série est dupliqué car l'organizer entre dans un dossier existant portant un nom légèrement différent (sans année). Plus généralement, quand un titre existe déjà en storage/symlinks sous une variante (nom différent, version différente), aucun mécanisme ne le détecte avant le transfert.

Le mécanisme CLI existant de gestion des conflits est jugé insatisfaisant et doit être remplacé.

## Objectifs

1. **Détection pré-transfert** : avant chaque transfert, détecter si un titre similaire existe déjà dans les répertoires symlinks (séries ET films)
   - Séries : scan des répertoires symlinks avec fuzzy matching sur le titre
   - Films : DB en priorité (tmdb_id), complété par un scan symlinks pour couvrir les trous

2. **Dialogue de comparaison** : présenter les deux versions côte-à-côte avec métadonnées techniques
   - Résolution (SD, 720p, 1080p, 4K)
   - Codec vidéo (H.264, H.265, AV1...)
   - Codec audio (AAC, AC3, DTS, TrueHD...)
   - Taille fichier
   - Langues disponibles

3. **Présélection intelligente** : calcul de score qualité pour recommander automatiquement la meilleure version (réutiliser/étendre le scoring qualité de la phase 31)

4. **Choix utilisateur** : 3 options
   - **Garder l'ancien** : annuler le transfert du nouveau fichier
   - **Garder le nouveau** : remplacer l'ancien (ancien → sandbox)
   - **Garder les deux** : transférer le nouveau, ancien → sandbox (permet un revert)

5. **Sandbox** : espace de stockage provisoire pour les anciennes versions
   - Récupérable sur demande (restauration)
   - Purgeable une fois certain du choix
   - Pattern similaire à la corbeille existante (trash)

6. **Parité CLI/Web** : mêmes fonctionnalités, affichage adapté
   - CLI : tableau Rich avec métadonnées, prompt interactif
   - Web : dialogue overlay avec comparaison visuelle

## Contraintes

- Réutiliser les patterns existants : corbeille provisoire, scoring qualité phase 31, fuzzy matching
- Le bug Gomorra (duplication répertoire par l'organizer) doit être résolu par cette détection en amont
- Ne pas casser le flux de transfert existant — la détection s'insère comme étape intermédiaire
- Performance : le scan des symlinks doit rester rapide (index mémoire, pas de rglob à chaque fichier)

## Périmètre hors-scope

- Détection de doublons DB (déjà traité en phase 31 avec check-duplicates)
- Gestion des doublons cross-genre dans les symlinks existants (deferred issue séparé)

## Questions ouvertes (à résoudre pendant le planning)

- Quel seuil de similarité pour la détection fuzzy ? (réutiliser le 0.85 existant ?)
- Faut-il un scan systématique ou seulement à la demande (option --check-duplicates) ?
- Emplacement de la sandbox : sous-dossier de trash ou dossier dédié ?
- Pour les séries : comparer épisode par épisode ou série entière ?
