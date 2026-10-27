from ibr.core.thumbs import (backup_ios_thumbnail, cache_name, ios_thumbnail, parse_thumbnailer, thumbnailer_argv,
                             thumbnailer_for)


def test_ios_thumbnail_for_camera_roll_files():
    expected = "/PhotoData/Thumbnails/V2/DCIM/100APPLE/IMG_0001.HEIC/5005.JPG"
    assert ios_thumbnail("/DCIM/100APPLE/IMG_0001.HEIC") == expected
    assert ios_thumbnail("/DCIM/100APPLE") is None
    assert ios_thumbnail("/Downloads/a.jpg") is None


def test_backup_ios_thumbnail():
    path = ("Camera Roll", "Media", "DCIM", "100APPLE", "IMG_0001.MOV")
    assert backup_ios_thumbnail(path) == ("Camera Roll", "Media", "PhotoData", "Thumbnails", "V2", "DCIM", "100APPLE",
                                          "IMG_0001.MOV", "5005.JPG")
    assert backup_ios_thumbnail(("Home", "Media", "DCIM", "100APPLE", "x.jpg")) is None
    assert backup_ios_thumbnail(("Camera Roll", "Media", "DCIM")) is None


def test_cache_name_is_stable_and_distinct():
    assert cache_name("a", 1) == cache_name("a", 1)
    assert cache_name("a", 1) != cache_name("a", 2)
    assert cache_name("a", 1).endswith(".png")


THUMBNAILER = """[Thumbnailer Entry]
TryExec=ffmpegthumbnailer
Exec=ffmpegthumbnailer -i %i -o %o -s %s -f
MimeType=video/mp4;video/quicktime;
"""


def test_parse_and_expand_thumbnailer():
    entry = parse_thumbnailer(THUMBNAILER)
    assert entry.try_exec == "ffmpegthumbnailer"
    assert entry.mime_types == ("video/mp4", "video/quicktime")
    argv = thumbnailer_argv(entry, "/tmp/a b.mp4", "/tmp/out.png", 256)
    assert argv == ["ffmpegthumbnailer", "-i", "/tmp/a b.mp4", "-o", "/tmp/out.png", "-s", "256", "-f"]
    uri = thumbnailer_argv(parse_thumbnailer(THUMBNAILER.replace("%i", "%u")), "/tmp/a b.mp4", "/o.png", 128)
    assert uri[2] == "file:///tmp/a%20b.mp4"


def test_parse_rejects_junk():
    assert parse_thumbnailer("nonsense") is None
    assert parse_thumbnailer("[Thumbnailer Entry]\nMimeType=a/b;\n") is None


def test_thumbnailer_for_mime_needs_installed_tool():
    entry = parse_thumbnailer(THUMBNAILER)
    assert thumbnailer_for([entry], "video/mp4", lambda tool: "/usr/bin/" + tool) is entry
    assert thumbnailer_for([entry], "video/mp4", lambda tool: None) is None
    assert thumbnailer_for([entry], "application/pdf", lambda tool: "/usr/bin/x") is None
