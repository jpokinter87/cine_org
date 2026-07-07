"""Exceptions du partage Jellyfin."""


class ShareError(Exception):
    """Erreur générique de préparation/teardown d'un partage."""


class ShareConflict(ShareError):
    """Un partage est déjà actif (et le remplacement n'a pas été confirmé)."""

    def __init__(self, active) -> None:
        self.active = active
        super().__init__(f"Partage déjà actif : {getattr(active, 'title', '?')}")
