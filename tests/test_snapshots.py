from datetime import datetime

from ibr.core.backups import scan_backups
from ibr.core.snapshots import create_snapshot, prune_snapshots
from test_backups import make_backup


def live(tmp_path, udid="AAA", date=datetime(2026, 10, 20, 9, 0)):
    folder = make_backup(tmp_path, udid, "Phone", date)
    (folder / "ab").mkdir()
    (folder / "ab" / "abcdef").write_bytes(b"old")
    return folder


def test_snapshot_hardlinks_files(tmp_path):
    folder = live(tmp_path)
    snap = create_snapshot(tmp_path, "AAA", "20261020-090000")
    assert snap == tmp_path / "snapshots" / "AAA" / "20261020-090000" / "AAA"
    assert (snap / "Info.plist").exists()
    assert (snap / "ab" / "abcdef").stat().st_ino == (folder / "ab" / "abcdef").stat().st_ino


def test_snapshot_survives_unlink_then_rewrite(tmp_path):
    folder = live(tmp_path)
    snap = create_snapshot(tmp_path, "AAA", "20261020-090000")
    target = folder / "ab" / "abcdef"
    target.unlink()
    target.write_bytes(b"new")
    assert (snap / "ab" / "abcdef").read_bytes() == b"old"


def test_prune_keeps_latest(tmp_path):
    live(tmp_path)
    for stamp in ("20261001-000000", "20261002-000000", "20261003-000000", "20261004-000000"):
        create_snapshot(tmp_path, "AAA", stamp)
    removed = prune_snapshots(tmp_path, "AAA", keep=3)
    assert [p.name for p in removed] == ["20261001-000000"]
    remaining = sorted(p.name for p in (tmp_path / "snapshots" / "AAA").iterdir())
    assert remaining == ["20261002-000000", "20261003-000000", "20261004-000000"]


def test_scan_prefers_snapshots_over_live(tmp_path):
    live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020-090000")
    create_snapshot(tmp_path, "AAA", "20261021-090000")
    entries = scan_backups(tmp_path)
    assert len(entries) == 2
    assert all(e.udid == "AAA" for e in entries)
    assert {e.restore_root.name for e in entries} == {"20261020-090000", "20261021-090000"}


def test_scan_live_without_snapshots(tmp_path):
    live(tmp_path)
    entries = scan_backups(tmp_path)
    assert len(entries) == 1
    assert entries[0].restore_root == tmp_path
    assert entries[0].path == tmp_path / "AAA"


def test_delete_older_snapshot_keeps_live(tmp_path):
    from ibr.core.snapshots import delete_backup
    live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020-090000")
    create_snapshot(tmp_path, "AAA", "20261021-090000")
    older = min(scan_backups(tmp_path), key=lambda e: e.restore_root.name)
    delete_backup(tmp_path, older)
    assert (tmp_path / "AAA").exists()
    assert [e.restore_root.name for e in scan_backups(tmp_path)] == ["20261021-090000"]


def test_delete_newest_snapshot_removes_live_too(tmp_path):
    from ibr.core.snapshots import delete_backup
    live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020-090000")
    create_snapshot(tmp_path, "AAA", "20261021-090000")
    newest = max(scan_backups(tmp_path), key=lambda e: e.restore_root.name)
    delete_backup(tmp_path, newest)
    assert not (tmp_path / "AAA").exists()
    assert [e.restore_root.name for e in scan_backups(tmp_path)] == ["20261020-090000"]


def test_delete_live_only_backup(tmp_path):
    from ibr.core.snapshots import delete_backup
    live(tmp_path)
    delete_backup(tmp_path, scan_backups(tmp_path)[0])
    assert scan_backups(tmp_path) == []


def test_new_stamp_is_utc_and_unique(tmp_path):
    from ibr.core.snapshots import new_stamp
    from datetime import timezone
    when = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    first = new_stamp(tmp_path, "AAA", when)
    assert first == "20261025T013000Z"
    (tmp_path / "snapshots" / "AAA" / first).mkdir(parents=True)
    assert new_stamp(tmp_path, "AAA", when) == "20261025T013000Z-1"


def test_snapshot_failure_keeps_existing_snapshots(tmp_path, monkeypatch):
    import os
    import pytest
    live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020T090000Z")

    def boom(*args, **kwargs):
        raise OSError("no links")
    monkeypatch.setattr(os, "link", boom)
    monkeypatch.setattr("ibr.core.snapshots._clone", lambda src, dst: False)
    with pytest.raises(OSError):
        create_snapshot(tmp_path, "AAA", "20261021T090000Z")
    names = sorted(p.name for p in (tmp_path / "snapshots" / "AAA").iterdir())
    assert names == ["20261020T090000Z"]


def test_partial_snapshots_are_ignored_and_pruned(tmp_path):
    live(tmp_path)
    partial = tmp_path / "snapshots" / "AAA" / "20261022T090000Z.partial" / "AAA"
    partial.mkdir(parents=True)
    (partial / "Info.plist").write_bytes((tmp_path / "AAA" / "Info.plist").read_bytes())
    create_snapshot(tmp_path, "AAA", "20261020T090000Z")
    assert [e.restore_root.name for e in scan_backups(tmp_path)] == ["20261020T090000Z"]
    prune_snapshots(tmp_path, "AAA", keep=3)
    assert not partial.parent.exists()


def test_live_newer_than_snapshots_is_listed(tmp_path):
    live(tmp_path, date=datetime(2026, 10, 20, 9, 0))
    create_snapshot(tmp_path, "AAA", "20261020T090000Z")
    make_backup_again = __import__("test_backups").make_backup
    import shutil
    for name in ("Info.plist", "Manifest.plist", "Status.plist"):
        (tmp_path / "AAA" / name).unlink()
    shutil.rmtree(tmp_path / "AAA" / "ab")
    (tmp_path / "AAA").rmdir()
    make_backup_again(tmp_path, "AAA", "Phone", datetime(2026, 10, 24, 9, 0))
    entries = scan_backups(tmp_path)
    assert [e.restore_root for e in entries] == [tmp_path, tmp_path / "snapshots" / "AAA" / "20261020T090000Z"]


def test_mark_damaged_when_copy_overwrote_shared_file(tmp_path):
    from ibr.core.snapshots import mark_damaged
    folder = live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020T090000Z")
    with open(folder / "ab" / "abcdef", "wb") as handle:
        handle.write(b"overwritten in place")
    damaged = mark_damaged(tmp_path, "AAA", ["ab/abcdef", "ab/missing"])
    assert [p.name for p in damaged] == ["20261020T090000Z"]
    entry = scan_backups(tmp_path)[0]
    assert entry.damaged


def test_mark_damaged_ignores_unshared_files(tmp_path):
    from ibr.core.snapshots import mark_damaged
    folder = live(tmp_path)
    create_snapshot(tmp_path, "AAA", "20261020T090000Z")
    target = folder / "ab" / "abcdef"
    target.unlink()
    target.write_bytes(b"new")
    assert mark_damaged(tmp_path, "AAA", ["ab/abcdef"]) == []
