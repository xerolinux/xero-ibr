import configparser
import hashlib
import shlex
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

THUMB_SIZE = 256
# iOS keeps a small JPEG of every Camera Roll photo and video here, on the device and in backups.
_IOS_THUMB = ("PhotoData", "Thumbnails", "V2")
_IOS_THUMB_FILE = "5005.JPG"


@dataclass(frozen=True)
class Thumbnailer:
    try_exec: str
    command: str
    mime_types: tuple[str, ...]


def ios_thumbnail(path: str) -> str | None:
    """The thumbnail iOS made for a Camera Roll file in the Media area, e.g. /DCIM/100APPLE/IMG_0001.HEIC."""
    parts = [p for p in path.split("/") if p]
    if len(parts) != 3 or parts[0] != "DCIM":
        return None
    return "/" + "/".join((*_IOS_THUMB, *parts, _IOS_THUMB_FILE))


def backup_ios_thumbnail(path: tuple[str, ...]) -> tuple[str, ...] | None:
    if len(path) != 5 or path[:3] != ("Camera Roll", "Media", "DCIM"):
        return None
    return (*path[:2], *_IOS_THUMB, *path[2:], _IOS_THUMB_FILE)


def cache_name(*identity) -> str:
    return hashlib.sha256(repr(identity).encode()).hexdigest()[:32] + ".png"


def parse_thumbnailer(text: str) -> Thumbnailer | None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
        entry = parser["Thumbnailer Entry"]
    except (configparser.Error, KeyError):
        return None
    command = entry.get("Exec", "").strip()
    if not command:
        return None
    mimes = tuple(m for m in entry.get("MimeType", "").split(";") if m)
    return Thumbnailer(entry.get("TryExec", "").strip() or shlex.split(command)[0], command, mimes)


def load_thumbnailers(folders: list[Path]) -> list[Thumbnailer]:
    found = []
    for folder in folders:
        for file in sorted(folder.glob("*.thumbnailer")) if folder.is_dir() else []:
            try:
                entry = parse_thumbnailer(file.read_text(errors="replace"))
            except OSError:
                continue
            if entry:
                found.append(entry)
    return found


def thumbnailer_for(entries: list[Thumbnailer], mime: str, which) -> Thumbnailer | None:
    return next((e for e in entries if mime in e.mime_types and which(e.try_exec)), None)


def thumbnailer_argv(entry: Thumbnailer, source: str, output: str, size: int) -> list[str]:
    values = {"%i": source, "%u": "file://" + quote(source), "%o": output, "%s": str(size), "%%": "%"}
    return [values.get(arg, arg) for arg in shlex.split(entry.command)]
