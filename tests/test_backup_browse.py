import os

import pytest
from backup_fixture import MODIFIED, PASSWORD, make_backup

from ibr.core.backup_browse import BackupReader, PasswordNeeded, WrongPassword, app_names, domain_folder


@pytest.fixture(params=[False, True], ids=["plain", "encrypted"])
def reader(request, tmp_path):
    folder = make_backup(tmp_path / "UDID", encrypted=request.param)
    return BackupReader.open(folder, PASSWORD if request.param else None)


def test_domain_folders():
    names = {"com.example.notes": "Notes Plus"}
    assert domain_folder("CameraRollDomain", names) == ("Camera Roll",)
    assert domain_folder("AppDomain-com.example.notes", names) == ("Apps", "Notes Plus")
    assert domain_folder("AppDomain-com.other", names) == ("Apps", "com.other")
    assert domain_folder("AppDomainGroup-group.x", names) == ("App Groups", "group.x")
    assert domain_folder("AppDomainPlugin-com.x.widget", names) == ("App Extensions", "com.x.widget")
    assert domain_folder("KeychainDomain", names) == ("System", "KeychainDomain")


def test_app_names_are_unique():
    import plistlib
    meta = plistlib.dumps({"itemName": "Mail"})
    info = {"Applications": {"a.one": {"iTunesMetadata": meta}, "b.two": {"iTunesMetadata": meta}, "c": {}}}
    assert app_names(info) == {"a.one": "Mail (a.one)", "b.two": "Mail (b.two)"}


def test_top_level_order_and_symlinks_hidden(reader):
    assert [n.name for n in reader.listing(())] == ["Camera Roll", "Home", "Apps", "App Groups", "System"]
    assert [n.name for n in reader.listing(("Home", "Library"))] == ["SMS"]


def test_file_details(reader):
    [photo] = reader.listing(("Camera Roll", "Media", "DCIM", "100APPLE"))
    details = reader.details(photo)
    assert not photo.is_dir
    assert details.size == len(b"jpeg bytes " * 50)
    assert details.modified.timestamp() == MODIFIED


def test_export_file_and_folder(reader, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    apps = reader.listing(("Apps",))
    result = reader.export([apps[0]], out, lambda *_: None)
    assert result.missing == 0
    note = out / "Notes Plus" / "Documents" / "note.txt"
    assert note.read_bytes() == b"hello note"
    assert int(os.stat(note).st_mtime) == MODIFIED
    reader.export([apps[0]], out, lambda *_: None)
    assert (out / "Notes Plus (2)" / "Documents" / "note.txt").exists()


def test_export_counts_missing_files(reader, tmp_path):
    [photo] = reader.listing(("Camera Roll", "Media", "DCIM", "100APPLE"))
    source = reader.source(photo)
    source.unlink()
    result = reader.export([photo], tmp_path, lambda *_: None)
    assert result.missing == 1


def test_encrypted_needs_the_right_password(tmp_path):
    folder = make_backup(tmp_path / "UDID", encrypted=True)
    with pytest.raises(PasswordNeeded):
        BackupReader.open(folder, None)
    with pytest.raises(WrongPassword):
        BackupReader.open(folder, "nope")
