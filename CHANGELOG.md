## v2.14.0 (2026-08-09)

### Feat

- **validation**: garde-fous contre l'éclatement des séries homonymes

## v2.13.1 (2026-08-09)

### Fix

- **validation**: cascade série après validation par ID externe

## v2.13.0 (2026-08-09)

### Feat

- **completude**: exporter la liste des épisodes manquants

## v2.12.0 (2026-08-09)

### Feat

- **completude**: afficher la qualité à rechercher pour les manques

## v2.11.0 (2026-08-09)

### Feat

- **web**: afficher le numéro de version dans le bandeau

## v2.10.0 (2026-08-09)

### Feat

- **completude**: prendre en compte les fichiers multi-épisodes

## v2.9.0 (2026-08-08)

### Feat

- **completude**: bouton « Revérifier » dans le cartouche de la fiche série

## v2.8.1 (2026-08-06)

### Fix

- **reassociation**: titres d'épisodes et fichiers alignés sur la fiche corrigée

## v2.8.0 (2026-08-05)

### Feat

- **web**: recalcul complétude en fin de transfert web
- **workflow**: recalcul complétude en fin de transfert CLI
- **completeness**: helper recompute_completeness_for_series

## v2.7.0 (2026-08-05)

### Feat

- **matching**: recherche séries via TMDB + résolution tvdb_id
- **matching**: helper _resolve_tvdb_candidates (TMDB -> tvdb_id)

## v2.6.0 (2026-08-05)

### Feat

- **library**: lien maintenance vers filtres granulaires + doc README
- **library**: deux cases 'Épisodes manquants'/'Saisons manquantes'
- **library**: filtres missing_episodes/missing_seasons dans browse
- **completeness**: migration 14 + backfill des flags de granularité
- **completeness**: check_series_model persiste has_missing_episodes/seasons
- **completeness**: colonnes has_missing_episodes/seasons sur SeriesModel

## v2.5.0 (2026-07-09)

### Fix

- **library**: conserver le filtre séries incomplètes et recalculer la complétude

## v2.4.2 (2026-07-08)

### Fix

- **share**: rafraîchir le bandeau immédiatement via HX-Trigger
- **share**: régénérer le bon bouton Partager après un départage
- **share**: indexer le partage via un scan de médiathèque Jellyfin

## v2.4.1 (2026-07-07)

### Fix

- **share**: robustesse teardown/erreurs Jellyfin + détection lecture Docker

## v2.4.0 (2026-07-07)

### Feat

- **share**: surveillance asyncio (démontage auto idle/plafond + auto-réparation)
- **share**: bouton sur les fiches film/série + bandeau global persistant
- **share**: endpoints web /share + bouton Partager/Départager + bandeau
- **share**: câblage DI (jellyfin_client, funnel_controller, share_service)
- **share**: ShareService (start/stop/replace + tick surveillance idle/plafond)
- **share**: JellyfinShareBuilder (émet 1 film/série dans l'arbre Partage)
- **share**: contrôleur Funnel Tailscale (runner subprocess injectable)
- **share**: client API Jellyfin (refresh bibliothèque + sessions)
- **share**: table ShareSession + repository (un partage actif)
- **share**: réglages config Jellyfin (url, clé API, dossier Partage)

## v2.3.0 (2026-06-28)

### Feat

- **jellyfin**: commande CLI jellyfin-sync
- **jellyfin**: synchronisation séries/épisodes et élagage --prune
- **jellyfin**: orchestration des films (isolation des erreurs)
- **jellyfin**: noms à plat et création idempotente des symlinks
- **jellyfin**: résolution source avec chaîne de repli
- **jellyfin**: génération NFO série et épisode
- **jellyfin**: génération NFO film (IDs + métadonnées complètes)
- **jellyfin**: dataclass JellyfinSyncReport
- **jellyfin**: réglage jellyfin_dir dans la configuration

### Fix

- **jellyfin**: collisions de dossier sans tmdb_id (suffixe index) via unique_folder_name

### Refactor

- **jellyfin**: état expected en paramètre + ordre déterministe des requêtes
- **jellyfin**: tree_builder robuste (année 0, ext, dir/symlink) + tests
- **jellyfin**: revue NFO — propriété cast_override, typage, tests de couverture

## v2.2.0 (2026-06-28)

### Feat

- **library**: menu déroulant « État » pour les filtres de la grille
- **player**: bouton scindé côté serveur (restauration après lecture)
- **player**: bouton « Visionner » scindé (lancement direct + chevron ▾)
- **player**: sélecteur d'identité dans l'en-tête + injection profil HTMX
- **player**: exposer get_personal_profiles aux templates
- **player**: get_personal_profiles() pour le sélecteur d'identité
- **library**: actions de la fiche détaillée sous la jaquette
- **transfer**: option « Garder l'ancien + corbeille » pour les doublons
- **relink**: ré-associer les fiches films sans fichier (relink-movies)
- **hardlinks**: porter le TTL de rétention par défaut de 30 à 60 jours

### Fix

- **library**: exclure les films du filtre « séries incomplètes »
- **player**: restaurer le bouton compact pour les parties de films
- **player**: encoder le profil en URL + test épisode + aria-label chevron

## v2.1.0 (2026-06-24)

### Feat

- **hardlinks**: purger aussi les fichiers résiduels non-vidéo des dossiers vidés
- **completeness**: badge 'Incomplet' et bloc justification sur la fiche série
- **completeness**: filtre 'séries incomplètes' dans la bibliothèque
- **completeness**: bouton + SSE de vérification sur la page Maintenance
- **completeness**: commande CLI check-completeness
- **completeness**: service de calcul CompletenessChecker
- **completeness**: TVDBClient.get_all_episodes (agrégation multi-saisons)
- **completeness**: colonnes de complétude sur SeriesModel + migration
- **merge**: supprimer les dossiers de symlinks vidés après la fusion
- **merge**: indicateur de chargement pendant la fusion (spinner + boutons désactivés)
- **merge**: UI — bouton conditionnel, merge.js, styles
- **merge**: routes web overlay + exécution de fusion
- **merge**: résolution conflits d'épisodes par qualité
- **merge**: merge() — rattachement, métadonnées, symlinks, archivage
- **merge**: preview() — comptage, conflits, métadonnées, avertissements
- **merge**: régénération du symlink canonique d'un épisode
- **merge**: dataclasses fusion séries + reconstruction MediaInfo

### Fix

- **completeness**: exposer completeness_status dans le dict série de la grille
- **merge**: afficher le bouton Fusionner (écouteur en capture) + libellé « Supprimer / Fusionner »
- **merge**: robustesse suite revue — erreurs structurées, feedback front, conflits sans état d'instance

## v2.0.0 (2026-06-20)

### Feat

- **version**: helper get_version() lisant pyproject.toml
- **cli**: commande link-movie-parts de rattachement des parties
- **films**: service MoviePartLinker de rattachement des parties orphelines
- **web**: cascade suppression des parties d'un film
- **web**: endpoint de lecture d'une partie de film
- **web**: bloc Parties sur la fiche film multi-parties
- **workflow**: enregistrer les parties >=2 comme MoviePart au transfert
- **workflow**: annoter les parties non primaires des films multi-parties
- **films**: modele MoviePartModel pour films multi-parties
- **library**: bouton de suppression des fiches fantômes (doublons)
- **series-enricher**: garde-fou anti-homonymes via comptes d'épisodes
- **library**: notes TMDB + IMDb pour les séries TV
- **phase-43-02**: bouton ✕ réutilisable sur inputs + debounce recherche 1000ms
- **phase-43-01**: recherche bibliothèque insensible aux accents via UDF SQLite
- **phase-42-02**: édition manuelle des métadonnées avec protection automatique
- **phase-42-01**: détection anomalies hors canon + override acceptance
- **phase-42-01**: socle DB overrides hors canon — SeasonOverrideModel + is_extra
- **ui**: bulles d'aide contextuelle sur config et maintenance
- **phase-40**: Lecteur DuneHD complet — UI config & validation
- **player**: backend DuneHD + bascule milestone v2.0→v2.1
- **rename-canonical**: commande de renommage des fichiers vers le titre DB
- **reassociate**: recherche par ID externe + métadonnées techniques + renommage symlink
- **phase-39**: hardlinks seeding — maintien du partage BitTorrent après transfert
- **phase-38**: déploiement production — systemd, deploy script, serve multi-workers
- **phase-37-02**: sandbox orphelins + fix sandbox subdivision critique
- **phase-37-01**: cross-genre DB, corbeille maintenance, Comédie dramatique
- **web**: bouton Visionner en validation manuelle
- **cli**: option --only pour cibler un type d'analyse cleanup
- **cleanup**: détection et correction des doublons cross-genre
- **web**: maintenance complète — corrections web, réconciliation DB, orphelins par symlinks

### Fix

- **cli**: la commande version lit la version réelle via get_version()
- **web**: créer les MoviePart au transfert web (chemin _update_db_paths)
- **library**: déduplication des séries aussi par tmdb_id
- **matching**: exclure strictement les séries documentaires des candidats
- **series-enricher**: pick_best_tv_match refuse les matches sans année alignée
- **matching**: améliorer précision association + scan qualité
- **organizer**: sanitize le titre des séries pour les noms de dossiers
- **reassociate**: extraction métadonnées techniques depuis symlink en fallback
- **sandbox**: réinjection dans downloads/Films ou downloads/Series selon type
- **web+cli**: corrections post-phase 36 — doublons, transfert, player
- **config**: rechargement à chaud après modification de la configuration
- **web+cli**: mise à jour DB après transfert + UX séries
- **web**: persistance état collapsed dans résolution doublons transfert
- **tmdb**: gérer les séries TV TMDB trouvées via recherche IMDB

### Refactor

- **web**: footer lit la version via le helper get_version()

### Perf

- **matching**: cache mémoire série pour éviter les recherches API redondantes + favicon

## v1.9.0 (2026-03-07)

### Feat

- **web**: badges qualité (résolution, codec, langue) sur posters grille
- **web**: résolution doublons pré-transfert dans le résumé batch
- **31-detection-doublons**: phase complete — CLI + vue web doublons
- **31-detection-doublons**: commande check-duplicates CLI
- **30-normalisation-series**: commandes migrate-series et fix-series-symlinks
- **29-films-multi-parties**: filet de sécurité doublons pour films découpés par le rippeur

### Fix

- **cli**: corriger AttributeError dans cleanup --fix (DuplicateSymlink + SubdivisionPlan)
- **web**: sandbox résout le vrai chemin storage via symlinks
- **web**: UX send-back → validation + dialogue confirmation transfert
- 6 corrections — transfert, cascade série, organizer, épisode 0, UX
- **web**: UX transfert + organizer accents + animation routing + scan filter

## v1.8.0 (2026-03-01)

### Feat

- **28-films-speciaux**: collections TMDB & vue sagas
- **27-performance-robustesse-matching**: cache TVDB bulk, compteurs workflow, VOSTFR
- **26-corrections-ux-mineures**: popover dynamique, profil Migré supprimé, reset workflow, logs serveur
- **25-reconciliation-symlinks-storage**: commande reconcile 3 phases + titres TVDB épisodes

## v1.7.0 (2026-03-01)

### Feat

- **24-refonte-filtres-bibliotheque**: refonte UX filtres bibliothèque — 2 lignes compactes

## v1.6.0 (2026-02-28)

### Feat

- **23-lectures-simultanees**: popover sélecteur profil + lectures parallèles — phase complete
- **22-suppression-bibliotheque**: suppression batch + corbeille réversible — phase complete
- **21-donnees-manquantes**: résolution données manquantes — phase complete
- **21-donnees-manquantes**: link-movies amélioré — 1040 films liés (82.5%)
- **20-navigation-affichage**: cartouches cliquables, genres normalisés, tri récemment ajouté — phase complete
- **player**: lecture distante Windows via watcher + SCP UTF-8

## v1.5.0 (2026-02-26)

### Feat

- **19-config-accordeon**: sections pliables + version dynamique footer — phase complete
- **18-reassociation-transfert**: ré-association transfert + validation — phase complete
- **18-reassociation-transfert**: bouton Renvoyer en validation + fix NullPool + dialogues custom — plan 01
- **17-visionner-surprends-moi**: bouton Visionner sur page Surprends-moi — phase complete
- **16-lecteur-distant**: lecteur configurable + profils nommés — phase complete
- **15-que-regarder-ce-soir**: watched/rating + page Surprends-moi — phase complete

### Fix

- **suggest**: navigation arrière/avant dans l'historique Surprends-moi

## v1.3.0 (2026-02-25)

### Feat

- **14-workflow-fluide**: boutons accès rapide workflow → validation → transfert
- **phase-13**: refactoring code — tests réparés, matching partagé, library découpé
- **12-dette-technique-donnees**: tri normalisé, recherche ligatures, enrichissement batch — phase complete

## v1.2.0 (2026-02-25)

### Feat

- **11-tableau-de-bord-qualite**: dashboard qualité — phase complete
- **pipeline**: propagation métadonnées techniques dans le workflow
- **library**: liens TVDB séries + fichier premier épisode + purge docs
- **library**: UX fiches détaillées — Multi langues, navigation flèches, genres cliquables
- **10-qualite**: détection automatique d'associations TMDB suspectes
- **09b-metadonnees-techniques**: filtres avancés, cartouches techniques et recherche étendue
- **library**: bouton Visionner — lancement mpv depuis les fiches web
- **09-correction-manuelle-associations**: ré-association TMDB manuelle avec indicateurs de confiance
- **08-fiches-detaillees**: liens externes, crédits cliquables et filtre par personne
- **06-07-enrichissement**: enrichissement films ratings + séries tmdb_id/imdb_id
- **05-bibliotheque-maintenance**: phase 5 complete — bibliothèque, config et maintenance web
- **05-bibliotheque-maintenance**: bibliothèque web, config, maintenance SSE et correction symlinks
- **cli**: ajouter la commande populate-series pour peupler la DB séries/épisodes
- **04-transfert-conflits**: page transfert web avec arborescence batch, SSE, conflits et dry-run
- **03-orchestration-workflow**: workflow web avec SSE temps réel et cascade séries
- **02-validation-visuelle**: validation visuelle complète avec HTMX
- **cli**: ajouter la commande fix-symlinks
- **01-foundation-web**: application FastAPI avec layout Jinja2, HTMX et page d'accueil stats
- **matching**: discrimination des candidats série par nombre d'épisodes TVDB
- **repair-links**: auto-réparation des séries et amélioration du workflow interactif
- **regroup**: ajouter une barre de progression pour --fix
- **organizer**: reconnaissance des sous-répertoires préfixe et commande regroup
- affichage détaillé en arbre pour toutes les catégories en dry-run
- détection symlinks dupliqués, suppression irréparables et --max-per-dir
- restreindre cleanup aux Films/Séries et ajouter cache d'analyse
- commande cleanup pour nettoyer et réorganiser video/
- récupération des titres français depuis TVDB
- auto-validation des épisodes de la même série
- alerte et proposition pour fichiers sous le seuil de taille
- feedback de sauvegarde avec notes lors du transfert de films
- enrichissement automatique des films avec notes TMDB et IMDb
- ajout commande enrich-imdb-ids pour récupérer les IDs IMDb depuis TMDB
- amélioration analyse générique avec EasyOCR et détection chapitres
- analyse du générique pour identification automatique (option a)
- options v (visionner) et y (YouTube trailer) dans validation
- auto-validation étendue pour haute confiance (1er >= 95%, autres < 70%)
- auto-validation dans validate manual pour candidat unique >= 95%
- enricher utilise le symlink en priorité pour l'extraction de titre
- extraction de titre via guessit pour meilleure correspondance
- améliorations UX repair-links et détection noms cryptiques
- optimisation repair-links et correction boucle infinie enrich
- commande consolidate pour rapatrier les fichiers externes
- amélioration UX de repair-links
- recherche floue pour la réparation des symlinks brisés
- import inversé depuis symlinks avec stockage dual path
- affichage enrichi des candidats et corrections multiples
- présentation arborescente des transferts avant validation
- structure unifiée storage/video et détection de contenu similaire
- classification des séries par type (TV/Animation/Mangas)
- récupération du titre d'épisode depuis TVDB
- **cli**: display transfer tree in dry-run mode
- **matching**: improve scoring with bilingual matching and adaptive coefficients

### Fix

- **library**: ré-association cassée + prefetch navigation + fallback VideoFile
- **09b**: corrections UAT — délai recherche et navigation retour
- convertir les symlinks relatifs en absolus et simplifier la navigation
- ajouter matching bilingue pour le scoring des séries TVDB
- **process**: auto-validation des épisodes basée sur l'ID TVDB, pas le dossier parent
- **parser**: gérer le cas où guessit retourne une liste pour season
- **regroup**: ne jamais toucher les fichiers de stockage lors du regroupement
- **regroup**: sauvegarder le répertoire analysé en cache pour --fix
- **prefix_grouper**: ne pas proposer de regroupement redondant avec un répertoire-titre ancêtre
- **organizer**: corriger le matching des plages asymétriques (A-Ami)
- **organizer**: navigation récursive des séries dans les subdivisions
- affiner les destinations hors-plage au niveau du plan et filtrer les faux répertoires de subdivision
- transferer les items hors plage vers le bon repertoire frere
- ajouter articles au/aux et filtrer la ponctuation dans les cles de tri
- corriger 7 bugs dans l'algorithme de subdivision des repertoires
- défaut "r" (recherche) quand aucun candidat disponible
- ajouter le candidat à la liste lors de l'auto-validation
- demander les titres français dans search() TVDB
- gestion erreur 404 TVDB lors de la recherche de séries
- ajout enrichissement et feedback dans workflow process
- titres en couleur dans enrich (vert=succès, rouge=échec)
- utiliser guessit pour extraire le titre dans enricher
- affichage propre de la commande enrich
- recherche complète au lieu de progressive pour repair-links
- clarification des messages repair-links
- exclure termes 3D du titre pour éviter faux positifs
- vérifier is_symlink avant is_dir pour éviter de suivre les symlinks cassés
- gestion des erreurs de permission lors de la recherche floue
- migration automatique pour ajouter symlink_path à la BDD existante
- correction détection contenu similaire et gestion staging
- résolution tolérante et titres d'épisodes en français
- resolution cinématographique et titre d'épisode
- **tvdb**: use TVDB API v3 instead of v4 for compatibility
- **scanner**: support French directory name "Séries" with accent
- multiple bugs in process workflow
- find .env relative to project root, not cwd

### Refactor

- supprimer import circulaire RepairService et nettoyer exports privés
- **tests**: découper test_cleanup.py en package tests/cleanup/
- **cli**: découper maintenance_commands.py en 5 fichiers séparés
- **services**: découper workflow.py en package workflow/
- **cli**: découper repair_helpers.py en package repair/
- **cli**: découper validation.py en package validation/
- **cleanup**: extraire cleanup.py dans le package cleanup/
- **integrity**: extraire RepairService dans le package repair/
- **cli**: centraliser console et helpers pour éliminer les imports circulaires
- **cli**: découper commands.py en 6 modules thématiques
- **commands**: utiliser les nouvelles fonctions de cache cleanup
- terminer le refactoring de _repair_links_async
- **commands**: extraire les helpers CLI pour consolidate
- **commands**: extraire les helpers CLI pour cleanup
- **commands**: simplifier validate batch avec batch_builder
- **commands**: extraire les helpers CLI pour repair-links
- **commands**: orchestrer le workflow via WorkflowService

### Perf

- recherche progressive par genre puis type puis base

## v1.0 (2026-01-28)

### Feat

- **08-02**: add CLI commands enrich, repair-links, check
- **08-02**: add IntegrityChecker and RepairService
- **08-01**: register import command in main.py and add CLI tests
- **08-01**: add import_library CLI command with progress bar
- **08-02**: add EnricherService with rate limiting
- **08-01**: add ImporterService with duplicate detection by hash
- **07-01**: add global callback verbose/quiet and mount validate_app
- **06-02**: create Typer commands for validation CLI
- **06-02**: create CLI validation module with Rich display
- **06-01**: wire ValidationService and API clients in DI container
- **06-01**: create ValidationService with business logic
- **05-02**: integrate Phase 5 services into DI container
- **05-02**: implement TransfererService with atomic move and symlinks
- **05-01**: ajouter QualityScorerService pour evaluation qualite video
- **05-01**: ajouter OrganizerService pour calcul chemins destination
- **05-01**: ajouter RenamerService pour generation noms fichiers
- **04-02**: integration repositories au container DI
- **04-02**: repositories SQLModel implementant les ports
- **04-02**: service de hash XXHash par echantillons
- **04-01**: modeles SQLModel avec index pour toutes les tables
- **04-01**: infrastructure SQLite avec engine et session factory
- **03-03**: implement TVDBClient with JWT authentication
- **03-02**: implement TMDBClient with cache-first pattern
- **03-04**: implement MatcherService for scoring API results
- **03-01**: implement APICache with TTL support (TDD)
- **02-02**: integrate DI container, ScannerService and CLI scan command
- **02-02**: add MediaInfoExtractor with unit tests
- **02-02**: add GuessitFilenameParser with TDD tests
- **02-01**: add FileSystemAdapter and ScannerService
- **02-01**: add parsing ports and value objects
- **01-02**: add CLI entry point with Typer
- **01-02**: add DI container with dependency-injector
- **01-02**: add configuration and logging infrastructure
- **01-01**: implement domain entities and port interfaces
- **01-01**: implement immutable value objects
- **01-01**: create hexagonal architecture structure

### Fix

- add missing dependencies and entry point to pyproject.toml
- **07-01**: remove await from sync database.init() calls
- **07**: revise plans based on checker feedback
- **06**: orchestrator corrections
- **06-02**: adapt CLI to existing architecture (no media_info.guessed)
- **03**: revise plans based on checker feedback

### Refactor

- **03-04**: remove unused _normalize_title function
- traduire documentation et messages en français
