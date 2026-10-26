import os

import pytest
from backup_fixture import ICON, MODIFIED, PASSWORD, make_backup

from ibr.core.app_catalog import AppMeta
from ibr.core.backup_browse import (BackupReader, PasswordNeeded, WrongPassword, app_catalog, domain_folder,
                                   tree_sections)


@pytest.fixture(params=[False, True], ids=["plain", "encrypted"])
def reader(request, tmp_path):
    folder = make_backup(tmp_path / "UDID", encrypted=request.param)
    return BackupReader.open(folder, PASSWORD if request.param else None)


APPS = {"com.example.notes": AppMeta("Notes Plus", None), "com.apple.mobilenotes": AppMeta("Notes", None)}


@pytest.mark.parametrize("domain, expected", [
    ("CameraRollDomain", ("Camera Roll",)),
    ("AppDomain-com.example.notes", ("Apps", "Notes Plus")),
    ("AppDomain-com.other", ("Apps", "com.other")),
    ("AppDomain-com.apple.AAUIViewService", ("System", "Apple Services", "com.apple.AAUIViewService")),
    ("AppDomainPlugin-com.example.notes.widget", ("Apps", "Notes Plus", "Extensions", "widget")),
    ("AppDomainPlugin-com.example.share", ("Apps", "Notes Plus", "Extensions", "com.example.share")),
    ("AppDomainPlugin-com.apple.foo.bar", ("System", "Extensions", "com.apple.foo.bar")),
    ("AppDomainGroup-group.com.example", ("Apps", "Notes Plus", "Shared", "group.com.example")),
    ("AppDomainGroup-ABCDE12345.groups.com.example.notes",
     ("Apps", "Notes Plus", "Shared", "ABCDE12345.groups.com.example.notes")),
    ("AppDomainGroup-group.com.apple.notes", ("Apps", "Notes", "Shared", "group.com.apple.notes")),
    ("AppDomainGroup-group.org.unknown", ("System", "Shared Groups", "group.org.unknown")),
    ("KeychainDomain", ("System", "KeychainDomain")),
])
def test_domain_folders(domain, expected):
    assert domain_folder(domain, APPS) == expected


def test_vendor_match_needs_a_single_app():
    apps = {"com.vendor.one": AppMeta("One", None), "com.vendor.two": AppMeta("Two", None)}
    assert domain_folder("AppDomainPlugin-com.vendor.widget", apps) == ("System", "Extensions", "com.vendor.widget")


def test_app_catalog_names_and_icons():
    import plistlib
    meta = plistlib.dumps({"itemName": "Mail"})
    info = {"Applications": {"a.one": {"iTunesMetadata": meta, "PlaceholderIcon": b"png"},
                             "b.two": {"iTunesMetadata": meta}, "c": {}}}
    saved = {"com.apple.mobilenotes": AppMeta("Notes", b"notes")}
    apps = app_catalog(info, saved)
    assert apps["a.one"] == AppMeta("Mail (a.one)", b"png")
    assert apps["b.two"] == AppMeta("Mail (b.two)", None)
    assert apps["com.apple.mobilenotes"] == AppMeta("Notes", b"notes")
    assert apps["com.apple.mobilesafari"] == AppMeta("Safari", None)
    assert "c" not in apps


def test_home_screen_name_beats_store_title():
    import plistlib
    info = {"Applications": {"com.discord": {"iTunesMetadata": plistlib.dumps({"itemName": "Discord – Talk, Play"}),
                                             "PlaceholderIcon": b"png"}}}
    apps = app_catalog(info, {"com.discord": AppMeta("Discord", None)})
    assert apps["com.discord"] == AppMeta("Discord", b"png")


def test_top_level_order_and_symlinks_hidden(reader):
    assert [n.name for n in reader.listing(())] == ["Home", "Camera Roll", "On My iPhone", "Apps", "System"]
    assert [n.name for n in reader.listing(("Home", "Library"))] == ["SMS"]


def test_apps_have_icons_and_their_shared_data(reader):
    files, notes, app = reader.listing(("Apps",))
    assert (files.name, notes.name, app.name) == ("Files", "Notes", "Notes Plus")
    assert reader.icon(app) == ICON
    assert reader.icon(notes) is None
    assert [n.name for n in reader.listing(("Apps", "Notes", "Shared"))] == ["group.com.apple.notes"]
    assert [n.name for n in reader.listing(("Apps", "Notes Plus"))] == ["Documents", "Shared"]
    assert reader.icon(reader.listing(("Apps", "Notes Plus"))[0]) is None
    assert reader.listing(("Apps", "Notes Plus"))[0].app is None


def test_saved_catalog_names_apple_apps(tmp_path):
    folder = make_backup(tmp_path / "UDID", encrypted=False)
    reader = BackupReader.open(folder, None, {"com.apple.mobilenotes": AppMeta("Notes", b"n")})
    assert [n.name for n in reader.listing(("Apps",))] == ["Files", "Notes", "Notes Plus"]
    assert reader.icon(reader.find(("Apps", "Notes"))) == b"n"


def test_file_details(reader):
    [photo] = reader.listing(("Camera Roll", "Media", "DCIM", "100APPLE"))
    details = reader.details(photo)
    assert not photo.is_dir
    assert details.size == len(b"jpeg bytes " * 50)
    assert details.modified.timestamp() == MODIFIED


def test_export_file_and_folder(reader, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    app = reader.find(("Apps", "Notes Plus"))
    result = reader.export([app], out, lambda *_: None)
    assert result.missing == 0
    note = out / "Notes Plus" / "Documents" / "note.txt"
    assert note.read_bytes() == b"hello note"
    assert int(os.stat(note).st_mtime) == MODIFIED
    reader.export([app], out, lambda *_: None)
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


def test_relabel_with_new_catalog(tmp_path):
    folder = make_backup(tmp_path / "UDID", encrypted=False)
    reader = BackupReader.open(folder, None)
    assert reader.icon(reader.find(("Apps", "Notes"))) is None
    reader.relabel({"com.apple.mobilenotes": AppMeta("Notes", b"n")})
    assert reader.icon(reader.find(("Apps", "Notes"))) == b"n"
    assert reader.find(("Apps", "Notes Plus", "Documents", "note.txt")) is not None


def test_on_my_iphone_shows_files_app_folders(reader):
    assert [n.name for n in reader.listing(("On My iPhone",))] == ["Downloads"]
    assert [n.name for n in reader.listing(("On My iPhone", "Downloads"))] == ["doc.pdf"]


def test_on_my_ipad(tmp_path):
    import plistlib
    folder = make_backup(tmp_path / "UDID", encrypted=False)
    info = plistlib.loads((folder / "Info.plist").read_bytes())
    info["Product Type"] = "iPad13,1"
    (folder / "Info.plist").write_bytes(plistlib.dumps(info))
    assert "On My iPad" in [n.name for n in BackupReader.open(folder, None).listing(())]


def test_tree_sections(reader):
    library, apps, system = tree_sections(reader)
    assert (library.title, library.path) == ("Library", ())
    assert [n.name for n in library.nodes] == ["Home", "Camera Roll", "On My iPhone"]
    assert (apps.title, apps.path) == ("Apps", ("Apps",))
    assert [n.name for n in apps.nodes] == ["Files", "Notes", "Notes Plus"]
    assert (system.title, [n.name for n in system.nodes]) == ("System", ["KeychainDomain"])
