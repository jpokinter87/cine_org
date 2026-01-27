# Phase 4: Persistance - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Stocker films, séries, épisodes et fichiers en attente dans une base SQLite avec SQLModel. Inclut les tables métier avec leurs relations, la table pending_validation pour le workflow de validation, la table trash pour l'historique des suppressions, et le calcul de hash pour la détection de doublons. Les index sont critiques car la vidéothèque contient >10000 entrées.

</domain>

<decisions>
## Implementation Decisions

### Structure des tables
- Métadonnées techniques essentielles uniquement : codec_video, codec_audio, resolution, langues, durée, taille
- Stockage des chemins : chemin complet + nom de fichier (redondant mais pratique pour les requêtes)

### Validation manuelle
- Table pending_validation stocke les candidats API (top 5) pour éviter de re-rechercher lors de la validation manuelle

### Gestion des doublons
- Algorithme de hash : XXHash (rapide, suffisant pour détection de doublons)
- Hash par échantillon : premiers/derniers Mo + taille (rapide, fiable en pratique)
- Comportement doublon détecté : signaler seulement, continuer le traitement, décision manuelle ultérieure
- Table trash : stockage complet des métadonnées du fichier supprimé (permet restauration)

### Performance et index
- Index sur tmdb_id, tvdb_id, imdb_id (vérification si déjà importé)
- Index sur title (recherche par nom)
- Volume attendu : >10000 entrées, optimisation critique

### Claude's Discretion
- Architecture tables : séparation series/episodes ou intégration, héritage media ou tables séparées
- Statuts du workflow de validation (pending, auto_validated, manual_validated, etc.)
- Niveau d'audit/traçabilité pour les validations
- Comportement après validation (supprimer de pending ou garder avec statut)
- Index sur file_hash selon la taille réelle de la BDD
- Choix migrations Alembic vs SQLModel create_all()

</decisions>

<specifics>
## Specific Ideas

- Candidats API stockés dans pending_validation évitent les appels API répétés lors de la validation manuelle
- Hash par échantillon = compromis vitesse/fiabilité pour fichiers vidéo volumineux (plusieurs Go)
- Table trash avec métadonnées complètes permet restauration si suppression par erreur

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-persistance*
*Context gathered: 2026-01-27*
