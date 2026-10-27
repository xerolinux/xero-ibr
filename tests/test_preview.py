from ibr.core.preview import converter_commands


def test_converter_commands_prefer_libheif_then_imagemagick():
    available = {"heif-dec", "magick"}
    commands = converter_commands("/in/IMG.HEIC", "/out/IMG.png", lambda tool: tool in available)
    assert commands == [["heif-dec", "/in/IMG.HEIC", "/out/IMG.png"], ["magick", "/in/IMG.HEIC", "/out/IMG.png"]]


def test_converter_commands_none_available():
    assert converter_commands("/in/a.heic", "/out/a.png", lambda tool: False) == []


def test_codec_hint_names_packages_outside_the_appimage():
    from ibr.core.preview import codec_hint
    assert "gst-libav" in codec_hint(appimage=False)
    assert "gst-plugins-ugly" in codec_hint(appimage=False)
    assert "gst-libav" not in codec_hint(appimage=True)
