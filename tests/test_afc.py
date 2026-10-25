import plistlib
from datetime import datetime

import pytest

from ibr.core.afc import AfcError, child_path, parent_path, parse_listing, sharing_apps

LISTING = (
    "drwxr-xr-x    3 mobile mobile        96 25 Oct 2026 12:00:00 DCIM\n"
    "-rw-r--r--    1 mobile mobile   1048576 24 Oct 2026 09:15:30 My Movie (final).mp4\n"
    "\x1b[36mlrwxrwxrwx    1 mobile mobile        10 01 Jan 2026 00:00:00 link\x1b[0m\n"
)


def test_parse_listing_dirs_first_then_names():
    entries = parse_listing(LISTING)
    assert [e.name for e in entries] == ["DCIM", "link", "My Movie (final).mp4"]
    movie = entries[2]
    assert movie.is_dir is False
    assert movie.size == 1048576
    assert movie.modified == datetime(2026, 10, 24, 9, 15, 30)
    assert entries[0].is_dir is True


def test_parse_listing_error_raises():
    with pytest.raises(AfcError, match="Permission denied"):
        parse_listing("Error: Failed to list '/x': Permission denied (10)\n")


def test_parse_listing_empty():
    assert parse_listing("") == []


def test_paths():
    assert child_path("/", "DCIM") == "/DCIM"
    assert child_path("/DCIM", "100APPLE") == "/DCIM/100APPLE"
    assert parent_path("/DCIM/100APPLE") == "/DCIM"
    assert parent_path("/DCIM") == "/"
    assert parent_path("/") == "/"


def test_child_path_rejects_traversal():
    with pytest.raises(AfcError):
        child_path("/DCIM", "../etc")
    with pytest.raises(AfcError):
        child_path("/DCIM", "a/b")


def test_sharing_apps_filters_and_sorts():
    data = plistlib.dumps([
        {"CFBundleIdentifier": "org.videolan.vlc-ios", "CFBundleDisplayName": "VLC", "UIFileSharingEnabled": True},
        {"CFBundleIdentifier": "com.example.nofiles", "CFBundleDisplayName": "No Files"},
        {"CFBundleIdentifier": "com.readdle.Documents", "CFBundleName": "Documents", "UIFileSharingEnabled": True},
    ])
    apps = sharing_apps(data)
    assert [(a.name, a.bundle_id) for a in apps] == [
        ("Documents", "com.readdle.Documents"),
        ("VLC", "org.videolan.vlc-ios"),
    ]


def test_sharing_apps_bad_data():
    assert sharing_apps(b"junk") == []


@pytest.mark.parametrize("name, is_dir, icon", [
    ("DCIM", True, "folder-symbolic"),
    ("IMG_0001.HEIC", False, "image-x-generic-symbolic"),
    ("clip.MOV", False, "video-x-generic-symbolic"),
    ("song.m4a", False, "audio-x-generic-symbolic"),
    ("notes.txt", False, "text-x-generic-symbolic"),
    ("noext", False, "text-x-generic-symbolic"),
])
def test_icon_for(name, is_dir, icon):
    from ibr.core.afc import icon_for
    assert icon_for(name, is_dir) == icon


@pytest.mark.parametrize("name, is_dir, kind", [
    ("IMG_0001.HEIC", False, "image"),
    ("photo.jpg", False, "image"),
    ("clip.MOV", False, "video"),
    ("song.m4a", False, "audio"),
    ("notes.txt", False, None),
    ("DCIM", True, None),
])
def test_media_kind(name, is_dir, kind):
    from ibr.core.afc import media_kind
    assert media_kind(name, is_dir) == kind


def test_breadcrumbs_relative_to_root():
    from ibr.core.afc import breadcrumbs
    assert breadcrumbs("/", "/", "Media") == [("Media", "/")]
    assert breadcrumbs("/DCIM/100APPLE", "/", "Media") == [("Media", "/"), ("DCIM", "/DCIM"),
                                                           ("100APPLE", "/DCIM/100APPLE")]
    assert breadcrumbs("/Documents", "/Documents", "VLC") == [("VLC", "/Documents")]
    assert breadcrumbs("/Documents/Movies", "/Documents", "VLC") == [("VLC", "/Documents"),
                                                                     ("Movies", "/Documents/Movies")]


def test_app_root():
    from ibr.core.afc import location_root
    assert location_root(None) == "/"
    assert location_root("org.videolan.vlc-ios") == "/Documents"
