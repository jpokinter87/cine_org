# Débogage des transferts NAS

Connaissances acquises en débogant des transferts depuis de vieux NAS (Synology) et disques
distants (`/media/wd10-*`) montés en NFS.

## Symptôme : rsync bloqué à ~99 % sur un gros fichier

- **Cause réelle** : le NAS Synology coupe à ~99 % à cause d'un `fsync` lent sur NFS (l'écriture
  est bufferisée puis le flush final timeout), **pas** un problème de bande passante.
- **Faux remède à ne pas reproduire** : la « séquence de débit dégressive » (réessayer de plus en
  plus lentement) part du postulat « si ça plante, c'est le débit » — **ce postulat est faux ici**.
  Ralentir n'aide pas et masque le vrai problème.
- **Pistes** : `rsync` sans `--bwlimit` ; surveiller le flush/fsync côté NFS ; viser un transfert
  simple et robuste plutôt qu'une logique de retry à vitesse dégressive.

## Symptôme : barre de progression trompeuse

- La barre et les chiffres affichés concernent **le total des fichiers**, pas le **fichier en cours**.
  Sur un gros fichier unique, l'utilisateur croit que c'est bloqué alors que le fichier copie.
- Amélioration attendue : afficher la progression **du fichier en cours** (octets), pas seulement le
  compteur global de fichiers.

## Règle générale

Avant d'ajouter de la complexité (retry, throttling, multi-passes), **mesurer empiriquement** où le
transfert bloque réellement. Ne pas supposer la cause.
