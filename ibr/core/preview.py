_CONVERTERS = ("heif-dec", "heif-convert", "magick")


def converter_commands(source: str, target: str, available) -> list[list[str]]:
    """System tools that can turn a photo GTK cannot decode (HEIC/HEIF) into a PNG, best first."""
    return [[tool, source, target] for tool in _CONVERTERS if available(tool)]
