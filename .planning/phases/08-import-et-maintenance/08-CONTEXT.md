# Phase 8: Import et Maintenance - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Importer une vidéothèque existante dans la BDD et fournir les outils de maintenance (symlinks, intégrité). Les commandes concernées sont : import, enrich, repair-links, check. Le workflow principal (process, pending, validate) est déjà implémenté en phase 7.

</domain>

<decisions>
## Implementation Decisions

### Comportement import
- Fichiers déjà connus (même hash) : ignorer silencieusement
- Fichiers sans match API : ajouter en pending_validation pour validation manuelle ultérieure
- Structure : respecter la hiérarchie existante (Films/ pour films, Séries/ pour séries)
- Verbosité par défaut : barre de progression + résumé final (X importés, Y ignorés, Z erreurs)

### Enrichissement API
- Rate limiting : respecter les limites API (TMDB: 40/10s) avec backoff exponentiel
- Reprise : naturellement résistant (relancer ne retraite pas les déjà enrichis, pas de checkpoint)
- Erreurs : retry 3 fois, puis skip et logger l'échec, continuer avec les suivants

### Claude's Discretion - Enrichissement
- Ordre de traitement des fichiers à enrichir (par date, score, alphabétique)

### Réparation symlinks
- Mode : interactif (demander confirmation pour chaque lien)
- Orphelins : déplacer vers trash (garder trace dans trash/orphans)
- Rapport : console + fichier log (repair-YYYY-MM-DD.log)

### Claude's Discretion - Réparation
- Stratégie de détection (scan video/ vs comparaison BDD/filesystem)

### Vérification intégrité
- Incohérences signalées : toutes (fichiers orphelins, entrées fantômes, symlinks cassés)
- Format rapport : texte structuré par défaut, --json pour format machine
- Actions correctives : suggestions (afficher les commandes à exécuter, pas de --fix auto)
- Hash : optionnel via --verify-hash (trop lent par défaut)

</decisions>

<specifics>
## Specific Ideas

- L'import respecte la structure existante de la vidéothèque (Films/Séries) pour déterminer le type
- Mode interactif pour repair-links pour éviter les suppressions accidentelles
- Logs des réparations pour audit ultérieur
- Suggestions de commandes dans check pour guider l'utilisateur vers la correction

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-import-et-maintenance*
*Context gathered: 2026-01-28*
