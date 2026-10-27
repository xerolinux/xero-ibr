_CONVERTERS = ("heif-dec", "heif-convert", "magick")


def converter_commands(source: str, target: str, available) -> list[list[str]]:
    """System tools that can turn a photo GTK cannot decode (HEIC/HEIF) into a PNG, best first."""
    return [[tool, source, target] for tool in _CONVERTERS if available(tool)]


def codec_hint(appimage: bool) -> str:
    """What to tell someone whose audio or video format could not be played."""
    if appimage:
        return "This format is not supported. Use Open in Default App to play it with your system player."
    return ("This format needs codecs that are not installed. Install gst-libav, gst-plugins-bad and "
            "gst-plugins-ugly, or use Open in Default App.")
