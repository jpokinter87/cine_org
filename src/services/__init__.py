"""
Couche services applicatifs (cas d'utilisation).

Les services orchestrent la logique métier pour réaliser les cas d'utilisation.
Ils coordonnent entre les entités, ports et systèmes externes.

Cette couche contient :
- Implémentations des cas d'utilisation
- Orchestration des workflows
- Gestion des transactions
- Gestion des erreurs au niveau applicatif

Les services dépendent des ports (interfaces) de core/, jamais des
implémentations concrètes de adapters/.
"""
