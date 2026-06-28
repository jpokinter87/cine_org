"""Tests du rapport de synchronisation Jellyfin."""

from src.services.jellyfin.dataclasses import JellyfinSyncReport


def test_report_defaults_are_empty():
    report = JellyfinSyncReport()
    assert report.movies == 0
    assert report.series == 0
    assert report.episodes == 0
    assert report.skipped == []
    assert report.id_less == []
    assert report.pruned == []
    assert report.errors == []


def test_report_accumulates():
    report = JellyfinSyncReport()
    report.movies += 1
    report.skipped.append("/x/y.mkv")
    assert report.movies == 1
    assert report.skipped == ["/x/y.mkv"]
