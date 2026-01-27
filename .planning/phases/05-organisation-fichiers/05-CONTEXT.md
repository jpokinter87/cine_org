# Phase 5: Organisation Fichiers - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Renommer les fichiers vidéo selon un format standardisé et les organiser dans une structure de répertoires avec symlinks. Les fichiers physiques vont dans `stockage/`, les symlinks dans `video/` reproduisent la même structure.

</domain>

<decisions>
## Implementation Decisions

### Format de renommage
- Ordre des éléments : `Titre (Année) Langue Codec Résolution.ext`
- Caractères spéciaux (: / \ * " < > |) remplacés par tiret (-)
- Point d'interrogation (?) remplacé par points de suspension (...)
- Ligatures françaises normalisées : œ → oe, Œ → Oe, æ → ae, Æ → Ae
- Longueur maximale : 200 caractères (hors extension)
- Langue audio : code ISO court (FR, EN, DE) ou "MULTi" si plusieurs pistes

### Structure des répertoires
- Articles ignorés pour le classement (Le, La, The, L') : "Le Parrain" classé sous P
- Titres numériques dans dossier "#" ou "0-9"
- Subdivision à 50 fichiers maximum par dossier
- Nommage des subdivisions : plage alphabétique (A-C, D-F)
- Précision dynamique selon besoin : Ab-Am, puis Mab-Mem si nécessaire

### Gestion des symlinks
- Chemins relatifs (portabilité si video/ et stockage/ restent ensemble)
- Structure miroir : video/ reproduit exactement la structure de stockage/
- Symlink existant à l'emplacement cible : demander confirmation avant remplacement
- Anciens symlinks avec structure différente : laissés tels quels (coexistence)
- Symlinks recréés : nouvelle structure miroir appliquée
- Migration complète : script de maintenance prévu en Phase 8

### Gestion des conflits
- Fichier existant à destination : vérifier le hash d'abord
- Vrai doublon (même hash) : choix complet proposé (garder existant / garder nouveau / garder les deux)
- Même nom mais hash différent : comparer qualité et suggérer la meilleure version
- Fonction de scoring multi-critères pour évaluer la qualité :
  - Résolution (30%) : 4K > 1080p > 720p > SD
  - Codec vidéo (25%) : AV1 > HEVC/H265 > H264 > anciens
  - Débit vidéo (20%) : normalisé par résolution
  - Audio (15%) : codec + canaux (7.1 > 5.1 > stereo) + débit
  - Taille (10%) : score inversé (plus petit = bonus, plafonné)

### Claude's Discretion
- Implémentation exacte de l'algorithme de scoring qualité
- Gestion des cas limites (fichiers sans métadonnées, codecs inconnus)
- Format exact des messages de confirmation utilisateur
- Stratégie de rollback en cas d'erreur pendant le transfert

</decisions>

<specifics>
## Specific Ideas

- Le scoring de qualité doit être affiché à l'utilisateur lors d'un conflit pour l'aider à choisir
- La subdivision dynamique permet d'adapter la profondeur selon la taille de la collection
- Les anciens symlinks coexistent avec les nouveaux jusqu'à migration manuelle

</specifics>

<deferred>
## Deferred Ideas

- Script de migration/harmonisation des anciens symlinks — Phase 8 (maintenance)

</deferred>

---

*Phase: 05-organisation-fichiers*
*Context gathered: 2026-01-27*
