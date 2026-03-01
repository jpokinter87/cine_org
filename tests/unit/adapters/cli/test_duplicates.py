"""Tests unitaires pour la commande check-duplicates."""

import json

from src.adapters.cli.commands.duplicates_command import (
    _build_media_info,
    _format_resolution,
    _format_size,
    _format_languages,
    _load_whitelist,
    _save_whitelist,
    _short_path,
)
from src.services.quality_scorer import calculate_quality_score


class TestBuildMediaInfo:
    """Tests pour _build_media_info."""

    def test_full_info(self):
        """Reconstruit un MediaInfo complet."""
        mi = _build_media_info("1920x1080", "x265", "AAC")
        assert mi is not None
        assert mi.resolution.width == 1920
        assert mi.resolution.height == 1080
        assert mi.video_codec.name == "x265"
        assert len(mi.audio_codecs) == 1
        assert mi.audio_codecs[0].name == "AAC"

    def test_resolution_only(self):
        """Reconstruit avec resolution seule."""
        mi = _build_media_info("1280x720", None, None)
        assert mi is not None
        assert mi.resolution.label == "720p"
        assert mi.video_codec is None

    def test_codec_only(self):
        """Reconstruit avec codec seul."""
        mi = _build_media_info(None, "x264", None)
        assert mi is not None
        assert mi.video_codec.name == "x264"
        assert mi.resolution is None

    def test_no_info(self):
        """Retourne None si aucune info."""
        mi = _build_media_info(None, None, None)
        assert mi is None

    def test_bad_resolution_format(self):
        """Gere un format de resolution invalide."""
        mi = _build_media_info("1080p", "x264", None)
        assert mi is not None
        assert mi.resolution is None
        assert mi.video_codec.name == "x264"

    def test_empty_resolution(self):
        """Gere une resolution vide."""
        mi = _build_media_info("", None, None)
        assert mi is None

    def test_4k_resolution(self):
        """Detecte la resolution 4K."""
        mi = _build_media_info("3840x2160", "x265", None)
        assert mi is not None
        assert mi.resolution.label == "4K"


class TestScoringComparison:
    """Tests pour la comparaison de qualite entre doublons."""

    def test_1080p_x265_beats_720p_x264(self):
        """1080p x265 > 720p x264."""
        mi_good = _build_media_info("1920x1080", "x265", "AAC")
        mi_bad = _build_media_info("1280x720", "x264", "AAC")

        score_good = calculate_quality_score(mi_good, 2_000_000_000, 7200)
        score_bad = calculate_quality_score(mi_bad, 1_000_000_000, 7200)

        assert score_good.total > score_bad.total

    def test_4k_beats_1080p(self):
        """4K > 1080p."""
        mi_4k = _build_media_info("3840x2160", "x265", "DTS-HD MA")
        mi_1080p = _build_media_info("1920x1080", "x264", "AAC")

        score_4k = calculate_quality_score(mi_4k, 8_000_000_000, 7200)
        score_1080p = calculate_quality_score(mi_1080p, 2_000_000_000, 7200)

        assert score_4k.total > score_1080p.total

    def test_same_quality_same_score(self):
        """Deux fichiers identiques ont le meme score."""
        mi1 = _build_media_info("1920x1080", "x264", "AAC")
        mi2 = _build_media_info("1920x1080", "x264", "AAC")

        score1 = calculate_quality_score(mi1, 1_500_000_000, 7200)
        score2 = calculate_quality_score(mi2, 1_500_000_000, 7200)

        assert score1.total == score2.total

    def test_no_info_gives_zero(self):
        """Pas d'info technique donne un score de 0."""
        score = calculate_quality_score(None, 0)
        assert score.total == 0


class TestWhitelist:
    """Tests pour le chargement/sauvegarde de la whitelist."""

    def test_load_missing_file(self, tmp_path):
        """Fichier absent retourne une whitelist vide."""
        wl = _load_whitelist(tmp_path / "missing.json")
        assert wl == {"whitelist": [], "notes": {}}

    def test_load_valid_file(self, tmp_path):
        """Charge une whitelist valide."""
        wl_path = tmp_path / "wl.json"
        wl_path.write_text(
            json.dumps({"whitelist": [123, 456], "notes": {"123": "test"}}),
            encoding="utf-8",
        )
        wl = _load_whitelist(wl_path)
        assert 123 in wl["whitelist"]
        assert 456 in wl["whitelist"]
        assert wl["notes"]["123"] == "test"

    def test_load_malformed_json(self, tmp_path):
        """Fichier JSON malformed retourne une whitelist vide."""
        wl_path = tmp_path / "bad.json"
        wl_path.write_text("{not valid", encoding="utf-8")
        wl = _load_whitelist(wl_path)
        assert wl == {"whitelist": [], "notes": {}}

    def test_load_missing_keys(self, tmp_path):
        """Fichier JSON sans les cles attendues les ajoute."""
        wl_path = tmp_path / "partial.json"
        wl_path.write_text("{}", encoding="utf-8")
        wl = _load_whitelist(wl_path)
        assert wl["whitelist"] == []
        assert wl["notes"] == {}

    def test_save_and_reload(self, tmp_path):
        """Sauvegarde et recharge correctement."""
        wl_path = tmp_path / "subdir" / "wl.json"
        data = {"whitelist": [789], "notes": {"789": "doublon volontaire"}}
        _save_whitelist(wl_path, data)

        assert wl_path.exists()
        reloaded = _load_whitelist(wl_path)
        assert reloaded == data


class TestFormatters:
    """Tests pour les fonctions de formatage."""

    def test_format_size_go(self):
        """Formate en Go."""
        assert _format_size(2_147_483_648) == "2.0 Go"

    def test_format_size_mo(self):
        """Formate en Mo."""
        assert _format_size(524_288_000) == "500 Mo"

    def test_format_size_none(self):
        """Retourne ? si None."""
        assert _format_size(None) == "?"

    def test_format_resolution_1080p(self):
        """Convertit en 1080p."""
        assert _format_resolution("1920x1080") == "1080p"

    def test_format_resolution_4k(self):
        """Convertit en 4K."""
        assert _format_resolution("3840x2160") == "4K"

    def test_format_resolution_720p(self):
        """Convertit en 720p."""
        assert _format_resolution("1280x720") == "720p"

    def test_format_resolution_sd(self):
        """Convertit en SD."""
        assert _format_resolution("720x480") == "SD"

    def test_format_resolution_none(self):
        """Retourne ? si None."""
        assert _format_resolution(None) == "?"

    def test_format_resolution_invalid(self):
        """Retourne ? si format invalide."""
        assert _format_resolution("1080p") == "?"

    def test_format_languages(self):
        """Formate les langues."""
        assert _format_languages('["fr", "en"]') == "FR, EN"

    def test_format_languages_none(self):
        """Retourne ? si None."""
        assert _format_languages(None) == "?"

    def test_short_path(self):
        """Extrait le nom de fichier."""
        assert _short_path("/media/NAS/Films/Action/Mon Film.mkv") == "Mon Film.mkv"

    def test_short_path_none(self):
        """Retourne ? si None."""
        assert _short_path(None) == "?"
