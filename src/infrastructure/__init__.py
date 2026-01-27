"""
Couche infrastructure de CineOrg.

Ce module contient les implementations concretes des interfaces definies
dans la couche domaine (ports). Il gere les preoccupations techniques :

- persistence/ : Stockage SQLite avec SQLModel (modeles et repositories)
- api/ : Clients HTTP pour TMDB et TVDB
- cache/ : Mise en cache des requetes API

Architecture hexagonale : les adapters ici implementent les ports du domaine,
permettant de changer l'implementation (ex: PostgreSQL au lieu de SQLite)
sans modifier la logique metier.
"""
