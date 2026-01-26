"""
CineOrg - Application de gestion de vidéothèque personnelle.

Ce package fournit les fonctionnalités pour scanner, identifier,
renommer et organiser les fichiers vidéo en utilisant les métadonnées TMDB et TVDB.

Architecture : Hexagonale (Ports et Adaptateurs)
- core/ : Couche domaine (entités, ports, objets valeur)
- services/ : Couche application (cas d'utilisation, orchestration)
- adapters/ : Couche infrastructure (CLI, Web, BDD, clients API)
"""
