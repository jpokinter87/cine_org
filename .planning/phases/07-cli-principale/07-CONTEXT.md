# Phase 7: CLI Principale - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Fournir les commandes CLI pour le workflow principal: scan, traitement et gestion des fichiers en attente. Les services métier (scanner, matcher, validation, transfert) sont déjà implémentés — cette phase les orchestre via Typer/Rich.

</domain>

<decisions>
## Implementation Decisions

### Workflow process
- Commande `process` exécute le workflow complet: scan → parsing → matching → auto-validation → validation interactive → transfert
- Options de filtrage: `--movies-only`, `--series-only`, `--movies-and-series` (défaut)
- Mode `--dry-run` pour simuler sans toucher aux fichiers
- Les fichiers sans correspondance (score < 85%) sont ajoutés à pending
- Après le matching, enchaîne automatiquement la validation interactive des fichiers en pending

### Affichage pending
- Commande `pending` affiche les fichiers en attente sous forme de cartes détaillées (panels Rich)
- Chaque carte montre tous les détails du fichier et ses candidats
- Tri par défaut: score décroissant (fichiers les plus faciles à valider en premier)
- Pas de filtrage (affiche toujours la liste complète)
- Pagination par défaut (10-20 fichiers), option `--all` pour tout voir

### Retour utilisateur
- Verbosité par défaut: verbose (détail de chaque fichier traité)
- Options `-v`/`--verbose` et `-q`/`--quiet` pour ajuster
- Barre de progression Rich pendant scan et matching (avec étape en cours et ETA)
- Couleurs toujours activées (vert=ok, jaune=pending, rouge=erreur)
- Résumé final: texte narratif + tableau de stats détaillé

### Gestion des erreurs
- Sur erreur: arrêt immédiat (fail-fast par défaut)
- Messages d'erreur style technique: "APIError: TMDB timeout after 30s on file X.mkv"
- Erreurs loggées en console (résumé) + fichier log JSON (détails complets)

### Claude's Discretion
- Codes de sortie (standards Unix ou détaillés)
- Nombre exact de fichiers par page pour pending
- Structure interne des commandes Typer

</decisions>

<specifics>
## Specific Ideas

- Workflow complet en une commande pour traiter un lot de téléchargements sans intervention manuelle jusqu'aux cas ambigus
- Verbose par défaut pour valider le fonctionnement au début, puis possibilité de repasser à normal une fois le programme fiable

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-cli-principale*
*Context gathered: 2026-01-28*
