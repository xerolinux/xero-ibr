from datetime import datetime, timedelta

from ibr.core.fmt import format_ago, format_date, format_eta, format_size, format_speed

NOW = datetime(2026, 10, 25, 12, 0)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(999) == "999 B"
    assert format_size(41_800_000_000) == "41.8 GB"
    assert format_size(256_000_000_000) == "256 GB"
    assert format_size(1_500_000) == "1.5 MB"
    assert format_size(2_000_000_000_000) == "2 TB"


def test_format_speed():
    assert format_speed(38_000_000) == "38 MB/s"


def test_format_date():
    assert format_date(datetime(2026, 10, 23, 21, 14)) == "23 Oct 2026, 21:14"


def test_format_ago():
    assert format_ago(NOW - timedelta(seconds=20), NOW) == "Just now"
    assert format_ago(NOW - timedelta(minutes=5), NOW) == "5 minutes ago"
    assert format_ago(NOW - timedelta(minutes=1), NOW) == "1 minute ago"
    assert format_ago(NOW - timedelta(hours=3), NOW) == "3 hours ago"
    assert format_ago(NOW - timedelta(days=1, hours=2), NOW) == "Yesterday"
    assert format_ago(NOW - timedelta(days=2), NOW) == "2 days ago"
    assert format_ago(NOW - timedelta(days=40), NOW) == "15 Sep 2026"
    assert format_ago(None, NOW) == "Never"


def test_format_eta():
    assert format_eta(None) == "Estimating…"
    assert format_eta(30) == "Under 1 min"
    assert format_eta(7 * 60 + 10) == "About 7 min"
    assert format_eta(65 * 60) == "About 1 h 5 min"
