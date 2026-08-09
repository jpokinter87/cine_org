"""
Profil de qualité cible d'une série incomplète.

Savoir qu'il manque « S01E12 » ne dit pas en quelle version la chercher.
Ce module dérive des épisodes réellement détenus la qualité dominante
(résolution, codecs, langues) pour la proposer comme cible.

Le calcul se fait par saison — les saisons récentes sont souvent mieux
encodées que les anciennes — avec repli sur la série entière quand la
saison concernée n'a aucune métadonnée exploitable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

# En deçà de cette part, la valeur dominante ne décrit plus vraiment le lot :
# le profil est signalé comme hétérogène plutôt que présenté comme une cible sûre.
_DOMINANCE_THRESHOLD = 2 / 3


@dataclass(frozen=True)
class QualityProfile:
    """Qualité dominante d'un ensemble d'épisodes détenus."""

    scope_label: str
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    languages: tuple[str, ...] = ()
    sample_size: int = 0
    mixed: bool = False

    @property
    def is_empty(self) -> bool:
        """Vrai si aucune caractéristique n'a pu être déterminée."""
        return not (
            self.resolution or self.video_codec or self.audio_codec or self.languages
        )

    @property
    def signature(self) -> tuple:
        """Caractéristiques hors périmètre, pour comparer deux profils."""
        return (
            self.resolution,
            self.video_codec,
            self.audio_codec,
            self.languages,
        )


def _dominant(values: Sequence[Any]) -> tuple[Any, bool]:
    """
    Retourne la valeur la plus fréquente et si sa dominance est faible.

    Args:
        values: valeurs renseignées (les absentes ont déjà été écartées).

    Returns:
        Tuple (valeur dominante ou None, dominance faible).
    """
    if not values:
        return None, False
    value, count = Counter(values).most_common(1)[0]
    return value, count / len(values) < _DOMINANCE_THRESHOLD


def compute_quality_profile(episodes: Iterable, scope_label: str) -> QualityProfile:
    """
    Calcule la qualité dominante d'un ensemble d'épisodes.

    Args:
        episodes: épisodes de la série (EpisodeModel) ; ceux sans fichier
            sont ignorés car ils ne décrivent aucune qualité détenue.
        scope_label: périmètre couvert, affiché tel quel (« Saison 01 »).

    Returns:
        Le profil dominant ; ``is_empty`` si rien n'est exploitable.
    """
    owned = [ep for ep in episodes if ep.file_path]
    if not owned:
        return QualityProfile(scope_label=scope_label)

    resolution, res_mixed = _dominant([ep.resolution for ep in owned if ep.resolution])
    video, video_mixed = _dominant([ep.codec_video for ep in owned if ep.codec_video])
    audio, audio_mixed = _dominant([ep.codec_audio for ep in owned if ep.codec_audio])
    languages, lang_mixed = _dominant(
        [tuple(sorted(ep.languages)) for ep in owned if ep.languages]
    )

    return QualityProfile(
        scope_label=scope_label,
        resolution=resolution,
        video_codec=video,
        audio_codec=audio,
        languages=languages or (),
        sample_size=len(owned),
        mixed=res_mixed or video_mixed or audio_mixed or lang_mixed,
    )


def _season_label(season: int) -> str:
    """Libellé de périmètre pour une saison."""
    return f"Saison {season:02d}"


def build_quality_targets(
    episodes: Sequence, detail: Optional[dict]
) -> list[QualityProfile]:
    """
    Construit les qualités à rechercher pour combler les manques d'une série.

    Une cible par saison ayant des épisodes manquants (calculée sur cette
    saison), plus une cible « série » si des saisons entières sont absentes.
    Les cibles identiques sont fusionnées en une seule, au périmètre « Série ».

    Args:
        episodes: tous les épisodes de la série (EpisodeModel).
        detail: détail de complétude persisté (``missing_seasons`` et
            ``missing_episodes``), ou None si la série n'a jamais été vérifiée.

    Returns:
        Liste de profils non vides, ordonnée par saison ; vide s'il n'y a
        rien à rechercher ou aucune métadonnée exploitable.
    """
    if not detail:
        return []

    missing_seasons = detail.get("missing_seasons") or []
    missing_episodes = detail.get("missing_episodes") or []
    if not missing_seasons and not missing_episodes:
        return []

    series_profile = compute_quality_profile(episodes, "Série")

    targets: list[QualityProfile] = []
    for season in sorted({ep["season"] for ep in missing_episodes}):
        in_season = [e for e in episodes if e.season_number == season]
        profile = compute_quality_profile(in_season, _season_label(season))
        # Une saison sans métadonnée n'apprend rien : emprunter celle de la série.
        if profile.is_empty:
            profile = series_profile
        targets.append(profile)

    if missing_seasons:
        targets.append(series_profile)

    targets = [t for t in targets if not t.is_empty]
    if not targets:
        return []

    # Plusieurs cibles qui coïncident : une seule ligne, au périmètre de la
    # série. Une cible unique garde son libellé de saison, plus informatif.
    if len(targets) > 1 and len({t.signature for t in targets}) == 1:
        first = targets[0]
        return [
            series_profile
            if series_profile.signature == first.signature
            else QualityProfile(
                scope_label="Série",
                resolution=first.resolution,
                video_codec=first.video_codec,
                audio_codec=first.audio_codec,
                languages=first.languages,
                sample_size=first.sample_size,
                mixed=first.mixed,
            )
        ]

    # Dédoublonner en conservant l'ordre (deux saisons peuvent partager un repli).
    unique: list[QualityProfile] = []
    seen: set[tuple] = set()
    for target in targets:
        key = (target.scope_label, target.signature)
        if key not in seen:
            seen.add(key)
            unique.append(target)
    return unique
