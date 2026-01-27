# Phase 3: Clients API - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Interroger TMDB et TVDB pour rechercher et récupérer les métadonnées films/séries avec gestion robuste du rate limiting. Le scoring classe les candidats, le cache réduit les appels API. La persistance en base et la validation manuelle sont des phases séparées.

</domain>

<decisions>
## Implementation Decisions

### Matching Strategy
- Scoring films: 50% titre + 25% année + 25% durée (défini dans roadmap)
- Tolérance année: ±1 an (pour gérer les variations de date de sortie)
- Tolérance durée: ±10% (pour gérer les variations d'encodage)
- Multiples candidats >= 85%: prendre le score le plus élevé (pas de validation manuelle si un candidat domine)
- Séries: 100% similarité titre + vérification numéros S/E (guessit S01E05 doit correspondre à l'API)

### Caching Policy
- Durées: 24h pour les recherches, 7j pour les détails (défini dans roadmap)
- Stockage: à la discrétion de Claude
- Persistance: le cache survit aux redémarrages de l'application
- Invalidation: expiration automatique + commande CLI manuelle disponible
- Taille: pas de limite (vidéothèque personnelle = volume gérable)

### Error Resilience
- Rate limit (429): Claude implémente retry + backoff exponentiel approprié
- API indisponible: continuer partiellement (traiter ce qui peut l'être, marquer le reste en pending)
- Max retries: à la discrétion de Claude selon les best practices
- Mode hors-ligne: non supporté (réseau requis pour le matching)

### Data Normalization
- Genres: toujours traduits en français (mapper les genres TMDB/TVDB)
- Champs requis films: titre + année + genre (genre nécessaire pour l'organisation répertoires)
- Champs requis séries: titre + année + titre d'épisode
- IDs externes: à la discrétion de Claude selon l'utilité future

### Claude's Discretion
- Mécanisme de stockage du cache (SQLite vs fichiers)
- Nombre de retries avant abandon
- Quels IDs externes stocker (IMDB, TMDB, TVDB)
- Stratégie exacte de backoff exponentiel
- Algorithme de similarité de titre

</decisions>

<specifics>
## Specific Ideas

- Le scoring doit être déterministe: même entrée = même résultat
- CLAUDE.md référence un mapping de genres TMDB vers français dans `src/utils/constants.py` (TMDB_GENRE_MAPPING)
- L'interface MediaAPIClient abstraite existe déjà (définie en Phase 1)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-clients-api*
*Context gathered: 2026-01-27*
