from ibr.core.app_catalog import AppMeta, load_saved, save_merged


def test_save_merges_with_what_was_saved(tmp_path):
    path = tmp_path / "apps" / "UDID.plist"
    save_merged(path, {"com.apple.mobilenotes": AppMeta("Notes", b"icon")})
    save_merged(path, {"com.apple.calculator": AppMeta("Calculator", None),
                       "com.apple.mobilenotes": AppMeta("Notes", None)})
    assert load_saved(path) == {"com.apple.mobilenotes": AppMeta("Notes", b"icon"),
                                "com.apple.calculator": AppMeta("Calculator", None)}


def test_missing_or_bad_file_is_empty(tmp_path):
    assert load_saved(tmp_path / "none.plist") == {}
    bad = tmp_path / "bad.plist"
    bad.write_bytes(b"nope")
    assert load_saved(bad) == {}


def test_visible_apps_skips_hidden_services():
    import plistlib

    from ibr.core.app_catalog import visible_apps
    data = plistlib.dumps([
        {"CFBundleIdentifier": "com.apple.Preferences", "CFBundleDisplayName": "Settings"},
        {"CFBundleIdentifier": "com.apple.AAUIViewService", "CFBundleName": "AAUI", "SBAppTags": ["hidden"]},
        {"CFBundleIdentifier": "com.example.app", "CFBundleName": "Example"},
        {"CFBundleIdentifier": "com.example.blank"},
        "junk",
    ])
    assert visible_apps(data) == {"com.apple.Preferences": "Settings", "com.example.app": "Example"}
    assert visible_apps(b"junk") == {}


def test_store_artwork_asks_for_small_png():
    import json

    from ibr.core.app_catalog import store_artwork
    data = json.dumps({"results": [
        {"bundleId": "com.apple.mobilenotes", "artworkUrl512": "https://x.mzstatic.com/a/b.png/512x512bb.jpg"},
        {"bundleId": "com.apple.calculator", "artworkUrl100": "https://x.mzstatic.com/c/d.png/100x100bb.jpg"},
        {"bundleId": "no.art"},
    ]}).encode()
    assert store_artwork(data) == {"com.apple.mobilenotes": "https://x.mzstatic.com/a/b.png/128x128bb.png",
                                   "com.apple.calculator": "https://x.mzstatic.com/c/d.png/128x128bb.png"}
    assert store_artwork(b"junk") == {}


def test_rounded_icon_has_clear_corners():
    import io

    import cairo

    from ibr.core.app_catalog import rounded_icon
    square = cairo.ImageSurface(cairo.FORMAT_RGB24, 128, 128)
    context = cairo.Context(square)
    context.set_source_rgb(1, 0, 0)
    context.paint()
    out = io.BytesIO()
    square.write_to_png(out)
    icon = cairo.ImageSurface.create_from_png(io.BytesIO(rounded_icon(out.getvalue())))
    pixels = icon.get_data()
    stride = icon.get_stride()
    assert pixels[3] == 0
    assert pixels[64 * stride + 64 * 4 + 3] == 255


def test_hidden_apple_apps_are_kept():
    import plistlib

    from ibr.core.app_catalog import visible_apps
    data = plistlib.dumps([{"CFBundleIdentifier": "com.apple.musicrecognition", "CFBundleName": "Music Recognition",
                            "SBAppTags": ["hidden"]}])
    assert visible_apps(data) == {"com.apple.musicrecognition": "Music Recognition"}
