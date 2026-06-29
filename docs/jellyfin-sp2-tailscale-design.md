# Jellyfin SP2 — Accès distant via Tailscale

**Statut** : spec validée (2026-06-29)
**Sous-projet** : 2/3 du plan d'intégration CineOrg → Jellyfin (cf. `jellyfin-sync-design.md` pour SP1)
**Nature** : tâche d'ops manuelle (≈ 90 %) + livrable documentaire (runbook README, mise à jour mémoire)

## Objectif

Permettre de regarder la bibliothèque Jellyfin depuis des appareils nomades **hors du
réseau local** (4G, autre Wi-Fi), sans exposer Jellyfin sur Internet et sans modifier
le conteneur Docker existant.

Périmètre SP2 = **les appareils personnels** (le serveur + plusieurs Android). Le partage
avec un tiers (ami distant du fils) et SyncPlay relèvent de **SP3** et sont hors périmètre ici.

## Contexte (acquis)

- Serveur Ubuntu 25.10 en `192.168.1.15`, **toujours allumé**, on peut y installer Tailscale.
- Jellyfin tourne en conteneur Docker (daemon système), écoute déjà sur `0.0.0.0:8096`.
- Accès **local** déjà fonctionnel (testé sur Android via `http://192.168.1.15:8096`).
- Appareils nomades : **Android** (plusieurs).
- **Pas de compte Tailscale existant** → création de zéro.

## Approche retenue : A — Tailscale sur le serveur + sur chaque Android

Un **tailnet privé** regroupe le serveur et les Android via un compte Tailscale unique.
Le serveur obtient une IP stable `100.x.x.x` (+ nom MagicDNS lisible). Une fois un Android
connecté au tailnet, il atteint `http://<serveur-tailnet>:8096` exactement comme en local,
quel que soit son réseau. Le trafic transite par le tunnel WireGuard chiffré ; **rien n'est
ouvert sur Internet**, et le conteneur Docker reste **inchangé**.

### Approches écartées

- **B — Tailscale Funnel (URL HTTPS publique)** : inutile, tous les appareils SP2 sont
  personnels et peuvent faire tourner Tailscale. N'ajoute que de la surface d'attaque.
  À reconsidérer éventuellement pour SP3 (et encore : le partage de nœud sera préférable).
- **C — Subnet router / exit node** : surdimensionné. Le serveur faisant lui-même tourner
  Tailscale, on tape directement son IP `100.x.x.x` — pas besoin d'annoncer `192.168.1.0/24`.

## Déroulé (ops, guidé pas à pas)

1. **Compte Tailscale** — création (login Google/GitHub/email), offre **Personal** gratuite.
2. **Serveur Ubuntu 25.10** — installation via le script officiel, `sudo tailscale up`,
   récupération de l'IP `100.x.x.x` et activation de **MagicDNS** (nom d'hôte lisible).
3. **Android** — appli Tailscale (Play Store), connexion au **même compte**, vérification
   que le téléphone voit le serveur dans la liste des machines.
4. **Vérification distante** — couper le Wi-Fi du téléphone (passer en 4G), ouvrir l'appli
   Jellyfin pointée sur `http://<nom-ou-IP-tailnet>:8096`, lancer une lecture.
5. **Confort (optionnel, noté pour plus tard)** — ajouter le sous-réseau Tailscale
   `100.64.0.0/10` aux « réseaux locaux » de Jellyfin (Tableau de bord → Réseau) pour qu'il
   traite ces clients comme du LAN (lecture directe, pas de transcodage inutile).

## Livrables côté dépôt

- **README** : nouvelle sous-section « Accès distant (Tailscale) » dans la section
  « Brancher Jellyfin », avec le runbook reproductible (commandes serveur, étapes Android,
  test 4G, dépannage courant).
- **Mémoire projet** (`jellyfin.md`) : marquer SP2 livré, consigner l'IP/nom tailnet et les
  écueils rencontrés.

## Hors périmètre SP2

- Comptes multi-utilisateurs et **SyncPlay** → SP3.
- Exposition publique / **Funnel**.
- **`tailscale serve`** / HTTPS sur le tailnet (amélioration reportée ; HTTP sur Tailscale
  est déjà chiffré par WireGuard).

## Critère de succès

Lecture d'un média Jellyfin depuis un Android **en 4G** (hors réseau local), via le tailnet,
sans rien avoir exposé publiquement.
