"""
Couche domaine (core).

Contient les entités métier, ports (interfaces abstraites), et objets valeur.
Cette couche n'a AUCUNE dépendance vers l'infrastructure (adapters, frameworks, BDD).

Sous-packages :
- entities/ : Entités métier (VideoFile, Movie, Series, Episode)
- ports/ : Interfaces abstraites définissant les contrats pour les adaptateurs
- value_objects/ : Objets valeur immutables (Resolution, Codec, Language)
"""
