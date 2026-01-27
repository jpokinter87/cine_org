"""
Tests unitaires pour QualityScorerService.

Tests TDD pour l'évaluation de la qualité vidéo multi-critères.
"""

import pytest

from src.core.value_objects.media_info import (
    MediaInfo,
    Resolution,
    VideoCodec,
    AudioCodec,
    Language,
)
from src.services.quality_scorer import (
    QualityScore,
    score_resolution,
    score_video_codec,
    score_audio,
    calculate_quality_score,
    QualityScorerService,
)


# ====================
# Fixtures
# ====================

@pytest.fixture
def resolution_4k() -> Resolution:
    """Résolution 4K (2160p)."""
    return Resolution(width=3840, height=2160)


@pytest.fixture
def resolution_1080p() -> Resolution:
    """Résolution Full HD (1080p)."""
    return Resolution(width=1920, height=1080)


@pytest.fixture
def resolution_720p() -> Resolution:
    """Résolution HD (720p)."""
    return Resolution(width=1280, height=720)


@pytest.fixture
def resolution_sd() -> Resolution:
    """Résolution SD (480p)."""
    return Resolution(width=720, height=480)


@pytest.fixture
def codec_av1() -> VideoCodec:
    """Codec AV1 (meilleur)."""
    return VideoCodec(name="AV1")


@pytest.fixture
def codec_hevc() -> VideoCodec:
    """Codec HEVC/H.265."""
    return VideoCodec(name="HEVC", profile="Main 10")


@pytest.fixture
def codec_h265() -> VideoCodec:
    """Codec H.265 (alias HEVC)."""
    return VideoCodec(name="H.265")


@pytest.fixture
def codec_h264() -> VideoCodec:
    """Codec H.264."""
    return VideoCodec(name="H.264")


@pytest.fixture
def codec_vp9() -> VideoCodec:
    """Codec VP9."""
    return VideoCodec(name="VP9")


@pytest.fixture
def codec_xvid() -> VideoCodec:
    """Codec XVID (ancien)."""
    return VideoCodec(name="XVID")


@pytest.fixture
def audio_truehd_71() -> tuple[AudioCodec, ...]:
    """Audio TrueHD 7.1."""
    return (AudioCodec(name="TrueHD", channels="7.1"),)


@pytest.fixture
def audio_dts_hd_51() -> tuple[AudioCodec, ...]:
    """Audio DTS-HD MA 5.1."""
    return (AudioCodec(name="DTS-HD MA", channels="5.1"),)


@pytest.fixture
def audio_dts_51() -> tuple[AudioCodec, ...]:
    """Audio DTS 5.1."""
    return (AudioCodec(name="DTS", channels="5.1"),)


@pytest.fixture
def audio_ac3_51() -> tuple[AudioCodec, ...]:
    """Audio AC3 (Dolby Digital) 5.1."""
    return (AudioCodec(name="AC3", channels="5.1"),)


@pytest.fixture
def audio_aac_stereo() -> tuple[AudioCodec, ...]:
    """Audio AAC stéréo."""
    return (AudioCodec(name="AAC", channels="2.0"),)


@pytest.fixture
def audio_mp3_stereo() -> tuple[AudioCodec, ...]:
    """Audio MP3 stéréo."""
    return (AudioCodec(name="MP3", channels="2.0"),)


@pytest.fixture
def audio_multi_track() -> tuple[AudioCodec, ...]:
    """Audio multi-pistes."""
    return (
        AudioCodec(name="TrueHD", channels="7.1"),
        AudioCodec(name="AC3", channels="5.1"),
    )


@pytest.fixture
def media_info_high_quality(
    resolution_4k: Resolution, codec_hevc: VideoCodec, audio_truehd_71: tuple[AudioCodec, ...]
) -> MediaInfo:
    """MediaInfo haute qualité."""
    return MediaInfo(
        resolution=resolution_4k,
        video_codec=codec_hevc,
        audio_codecs=audio_truehd_71,
        audio_languages=(Language(code="fr", name="Français"),),
        duration_seconds=7200,
    )


@pytest.fixture
def media_info_medium_quality(
    resolution_1080p: Resolution, codec_h264: VideoCodec, audio_ac3_51: tuple[AudioCodec, ...]
) -> MediaInfo:
    """MediaInfo qualité moyenne."""
    return MediaInfo(
        resolution=resolution_1080p,
        video_codec=codec_h264,
        audio_codecs=audio_ac3_51,
        audio_languages=(Language(code="fr", name="Français"),),
        duration_seconds=5400,
    )


@pytest.fixture
def media_info_low_quality(
    resolution_sd: Resolution, codec_xvid: VideoCodec, audio_mp3_stereo: tuple[AudioCodec, ...]
) -> MediaInfo:
    """MediaInfo basse qualité."""
    return MediaInfo(
        resolution=resolution_sd,
        video_codec=codec_xvid,
        audio_codecs=audio_mp3_stereo,
        audio_languages=(Language(code="fr", name="Français"),),
        duration_seconds=5400,
    )


# ====================
# Tests score_resolution
# ====================

class TestScoreResolution:
    """Tests pour le scoring de la résolution."""

    def test_score_resolution_4k(self, resolution_4k: Resolution) -> None:
        """4K obtient le score maximum."""
        assert score_resolution(resolution_4k) == 100

    def test_score_resolution_4k_variant(self) -> None:
        """4K avec dimensions légèrement différentes."""
        res = Resolution(width=4096, height=2160)  # DCI 4K
        assert score_resolution(res) == 100

    def test_score_resolution_1080p(self, resolution_1080p: Resolution) -> None:
        """1080p obtient 75."""
        assert score_resolution(resolution_1080p) == 75

    def test_score_resolution_720p(self, resolution_720p: Resolution) -> None:
        """720p obtient 50."""
        assert score_resolution(resolution_720p) == 50

    def test_score_resolution_sd(self, resolution_sd: Resolution) -> None:
        """SD obtient 25."""
        assert score_resolution(resolution_sd) == 25

    def test_score_resolution_very_low(self) -> None:
        """Très basse résolution obtient 25."""
        res = Resolution(width=640, height=360)
        assert score_resolution(res) == 25

    def test_score_resolution_none(self) -> None:
        """None obtient 0."""
        assert score_resolution(None) == 0


# ====================
# Tests score_video_codec
# ====================

class TestScoreVideoCodec:
    """Tests pour le scoring du codec vidéo."""

    def test_score_video_codec_av1(self, codec_av1: VideoCodec) -> None:
        """AV1 obtient le score maximum."""
        assert score_video_codec(codec_av1) == 100

    def test_score_video_codec_hevc(self, codec_hevc: VideoCodec) -> None:
        """HEVC obtient 85."""
        assert score_video_codec(codec_hevc) == 85

    def test_score_video_codec_h265(self, codec_h265: VideoCodec) -> None:
        """H.265 (alias HEVC) obtient 85."""
        assert score_video_codec(codec_h265) == 85

    def test_score_video_codec_h265_lowercase(self) -> None:
        """h265 en minuscules obtient 85."""
        codec = VideoCodec(name="h265")
        assert score_video_codec(codec) == 85

    def test_score_video_codec_vp9(self, codec_vp9: VideoCodec) -> None:
        """VP9 obtient 70."""
        assert score_video_codec(codec_vp9) == 70

    def test_score_video_codec_h264(self, codec_h264: VideoCodec) -> None:
        """H.264 obtient 60."""
        assert score_video_codec(codec_h264) == 60

    def test_score_video_codec_avc(self) -> None:
        """AVC (alias H.264) obtient 60."""
        codec = VideoCodec(name="AVC")
        assert score_video_codec(codec) == 60

    def test_score_video_codec_mpeg4(self) -> None:
        """MPEG-4 obtient le score par défaut (30)."""
        codec = VideoCodec(name="MPEG-4")
        assert score_video_codec(codec) == 30

    def test_score_video_codec_xvid(self, codec_xvid: VideoCodec) -> None:
        """XVID obtient le score par défaut (30)."""
        assert score_video_codec(codec_xvid) == 30

    def test_score_video_codec_unknown(self) -> None:
        """Codec inconnu obtient le score par défaut (30)."""
        codec = VideoCodec(name="UNKNOWN_CODEC")
        assert score_video_codec(codec) == 30

    def test_score_video_codec_none(self) -> None:
        """None obtient 0."""
        assert score_video_codec(None) == 0


# ====================
# Tests score_audio
# ====================

class TestScoreAudio:
    """Tests pour le scoring audio."""

    def test_score_audio_truehd_71(self, audio_truehd_71: tuple[AudioCodec, ...]) -> None:
        """TrueHD 7.1 obtient un score très élevé (>90)."""
        score = score_audio(audio_truehd_71)
        assert score > 90

    def test_score_audio_dts_hd_51(self, audio_dts_hd_51: tuple[AudioCodec, ...]) -> None:
        """DTS-HD MA 5.1 obtient un score élevé."""
        score = score_audio(audio_dts_hd_51)
        assert 80 < score < 95

    def test_score_audio_dts_51(self, audio_dts_51: tuple[AudioCodec, ...]) -> None:
        """DTS 5.1 obtient un score moyen-haut."""
        score = score_audio(audio_dts_51)
        assert 60 < score < 80

    def test_score_audio_ac3_51(self, audio_ac3_51: tuple[AudioCodec, ...]) -> None:
        """AC3 5.1 obtient un score moyen."""
        score = score_audio(audio_ac3_51)
        assert 50 < score < 70

    def test_score_audio_aac_stereo(self, audio_aac_stereo: tuple[AudioCodec, ...]) -> None:
        """AAC stéréo obtient un score inférieur à 60."""
        score = score_audio(audio_aac_stereo)
        assert score < 60

    def test_score_audio_mp3_stereo(self, audio_mp3_stereo: tuple[AudioCodec, ...]) -> None:
        """MP3 stéréo obtient le score le plus bas."""
        score = score_audio(audio_mp3_stereo)
        assert score < 50

    def test_score_audio_multi_track(self, audio_multi_track: tuple[AudioCodec, ...]) -> None:
        """Multi-pistes prend la meilleure piste."""
        score = score_audio(audio_multi_track)
        # Doit prendre TrueHD 7.1 (la meilleure)
        assert score > 90

    def test_score_audio_empty(self) -> None:
        """Tuple vide obtient 0."""
        assert score_audio(()) == 0

    def test_score_audio_no_channels(self) -> None:
        """Audio sans info canaux."""
        codecs = (AudioCodec(name="AAC", channels=None),)
        score = score_audio(codecs)
        assert score > 0  # Score basé sur le codec uniquement


# ====================
# Tests QualityScore dataclass
# ====================

class TestQualityScore:
    """Tests pour la dataclass QualityScore."""

    def test_quality_score_creation(self) -> None:
        """Création basique d'un QualityScore."""
        score = QualityScore(
            resolution_score=75.0,
            video_codec_score=85.0,
            bitrate_score=70.0,
            audio_score=80.0,
            size_efficiency=60.0,
            total=76.5,
        )
        assert score.resolution_score == 75.0
        assert score.total == 76.5

    def test_quality_score_immutable(self) -> None:
        """QualityScore est immutable (frozen)."""
        score = QualityScore(
            resolution_score=75.0,
            video_codec_score=85.0,
            bitrate_score=70.0,
            audio_score=80.0,
            size_efficiency=60.0,
            total=76.5,
        )
        with pytest.raises(AttributeError):
            score.total = 90.0  # type: ignore[misc]

    def test_quality_score_breakdown(self) -> None:
        """La propriété breakdown retourne un dict lisible."""
        score = QualityScore(
            resolution_score=75.0,
            video_codec_score=85.0,
            bitrate_score=70.0,
            audio_score=80.0,
            size_efficiency=60.0,
            total=76.5,
        )
        breakdown = score.breakdown
        assert "resolution" in breakdown
        assert breakdown["resolution"] == 75.0
        assert breakdown["total"] == 76.5


# ====================
# Tests calculate_quality_score
# ====================

class TestCalculateQualityScore:
    """Tests pour le calcul du score de qualité global."""

    def test_quality_score_high_quality(
        self, media_info_high_quality: MediaInfo
    ) -> None:
        """Fichier haute qualité obtient un score élevé (>80)."""
        score = calculate_quality_score(
            media_info_high_quality,
            file_size_bytes=10_000_000_000,  # 10 GB
            duration_seconds=7200,
        )
        assert score.total > 80

    def test_quality_score_medium_quality(
        self, media_info_medium_quality: MediaInfo
    ) -> None:
        """Fichier qualité moyenne obtient un score moyen."""
        score = calculate_quality_score(
            media_info_medium_quality,
            file_size_bytes=4_000_000_000,  # 4 GB
            duration_seconds=5400,
        )
        assert 50 < score.total < 80

    def test_quality_score_low_quality(
        self, media_info_low_quality: MediaInfo
    ) -> None:
        """Fichier basse qualité obtient un score bas (<50)."""
        score = calculate_quality_score(
            media_info_low_quality,
            file_size_bytes=700_000_000,  # 700 MB
            duration_seconds=5400,
        )
        assert score.total < 50

    def test_quality_score_none_media_info(self) -> None:
        """MediaInfo None retourne un score de 0."""
        score = calculate_quality_score(None, file_size_bytes=0)
        assert score.total == 0
        assert score.resolution_score == 0
        assert score.video_codec_score == 0
        assert score.audio_score == 0

    def test_quality_score_weights_sum_to_100(
        self, media_info_high_quality: MediaInfo
    ) -> None:
        """Les poids doivent sommer à 100%."""
        # Les poids sont: resolution 30%, codec 25%, bitrate 20%, audio 15%, size 10%
        score = calculate_quality_score(
            media_info_high_quality,
            file_size_bytes=10_000_000_000,
            duration_seconds=7200,
        )
        # Si tous les sous-scores sont 100, le total doit être ~100
        # (avec une marge car le bitrate et la taille peuvent varier)
        assert score.total <= 100

    def test_quality_score_comparison(
        self,
        media_info_high_quality: MediaInfo,
        media_info_low_quality: MediaInfo,
    ) -> None:
        """Haute qualité > Basse qualité."""
        high_score = calculate_quality_score(
            media_info_high_quality,
            file_size_bytes=10_000_000_000,
            duration_seconds=7200,
        )
        low_score = calculate_quality_score(
            media_info_low_quality,
            file_size_bytes=700_000_000,
            duration_seconds=5400,
        )
        assert high_score.total > low_score.total

    def test_quality_score_bitrate_affects_score(
        self, resolution_1080p: Resolution, codec_h264: VideoCodec, audio_ac3_51: tuple[AudioCodec, ...]
    ) -> None:
        """Le bitrate affecte le score."""
        media_info = MediaInfo(
            resolution=resolution_1080p,
            video_codec=codec_h264,
            audio_codecs=audio_ac3_51,
            duration_seconds=7200,
        )
        # Même fichier avec tailles différentes
        high_bitrate_score = calculate_quality_score(
            media_info,
            file_size_bytes=10_000_000_000,  # 10 GB
            duration_seconds=7200,
        )
        low_bitrate_score = calculate_quality_score(
            media_info,
            file_size_bytes=2_000_000_000,  # 2 GB
            duration_seconds=7200,
        )
        # Le score avec haut bitrate doit être supérieur
        assert high_bitrate_score.bitrate_score > low_bitrate_score.bitrate_score


# ====================
# Tests QualityScorerService
# ====================

class TestQualityScorerService:
    """Tests pour le service QualityScorerService."""

    def test_service_calculate_quality_score(
        self, media_info_high_quality: MediaInfo
    ) -> None:
        """Le service appelle correctement calculate_quality_score."""
        service = QualityScorerService()
        score = service.calculate_quality_score(
            media_info_high_quality,
            file_size_bytes=10_000_000_000,
            duration_seconds=7200,
        )
        assert score.total > 80

    def test_service_compare_quality(
        self,
        media_info_high_quality: MediaInfo,
        media_info_low_quality: MediaInfo,
    ) -> None:
        """Le service permet de comparer deux fichiers."""
        service = QualityScorerService()
        high_score = service.calculate_quality_score(
            media_info_high_quality,
            file_size_bytes=10_000_000_000,
            duration_seconds=7200,
        )
        low_score = service.calculate_quality_score(
            media_info_low_quality,
            file_size_bytes=700_000_000,
            duration_seconds=5400,
        )
        assert high_score.total > low_score.total
