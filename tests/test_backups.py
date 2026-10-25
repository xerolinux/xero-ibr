import plistlib
from datetime import datetime

from ibr.core.backups import dir_size, scan_backups


def make_backup(root, udid, name, date, encrypted=True, state="finished", product="iPhone17,1"):
    folder = root / udid
    folder.mkdir()
    (folder / "Info.plist").write_bytes(plistlib.dumps({
        "Device Name": name,
        "Product Type": product,
        "Product Version": "26.0.1",
        "Last Backup Date": date,
    }))
    (folder / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": encrypted}))
    (folder / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": state}))
    return folder


def test_scan_sorted_newest_first(tmp_path):
    make_backup(tmp_path, "AAA", "Old", datetime(2026, 9, 1, 10, 0))
    make_backup(tmp_path, "BBB", "New", datetime(2026, 10, 23, 21, 14), encrypted=False)
    entries = scan_backups(tmp_path)
    assert [e.udid for e in entries] == ["BBB", "AAA"]
    newest = entries[0]
    assert newest.device_name == "New"
    assert newest.product_type == "iPhone17,1"
    assert newest.os_version == "26.0.1"
    assert newest.date == datetime(2026, 10, 23, 21, 14)
    assert newest.encrypted is False
    assert newest.complete is True


def test_incomplete_backup_flagged(tmp_path):
    make_backup(tmp_path, "AAA", "Phone", datetime(2026, 9, 1), state="new")
    assert scan_backups(tmp_path)[0].complete is False


def test_folders_without_info_are_skipped(tmp_path):
    (tmp_path / "random").mkdir()
    (tmp_path / "file.txt").write_text("x")
    assert scan_backups(tmp_path) == []


def test_corrupt_info_is_skipped(tmp_path):
    folder = tmp_path / "AAA"
    folder.mkdir()
    (folder / "Info.plist").write_bytes(b"garbage")
    assert scan_backups(tmp_path) == []


def test_missing_root_returns_empty(tmp_path):
    assert scan_backups(tmp_path / "nope") == []


def test_missing_date_sorts_last(tmp_path):
    folder = make_backup(tmp_path, "AAA", "Dated", datetime(2026, 1, 1))
    other = tmp_path / "BBB"
    other.mkdir()
    (other / "Info.plist").write_bytes(plistlib.dumps({"Device Name": "Undated"}))
    entries = scan_backups(tmp_path)
    assert [e.udid for e in entries] == ["AAA", "BBB"]
    assert entries[1].date is None
    assert folder.exists()


def test_dir_size(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"y" * 50)
    assert dir_size(tmp_path) == 150
