import plistlib
import re
from dataclasses import dataclass
from datetime import datetime


class AfcError(Exception):
    pass


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    is_dir: bool
    size: int
    modified: datetime | None


@dataclass(frozen=True)
class SharingApp:
    bundle_id: str
    name: str


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LINE = re.compile(r"^([dl\-fbcs])\S{9}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2}) (.+)$")


def check_output(text: str) -> str:
    for line in _ANSI.sub("", text).splitlines():
        if line.startswith("Error:"):
            message = line[len("Error:"):].strip()
            raise AfcError(re.sub(r"\s*\(-?\d+\)$", "", message.split(": ", 1)[-1]))
    return text


def parse_listing(text: str) -> list[RemoteEntry]:
    entries = []
    for line in _ANSI.sub("", check_output(text)).splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        kind, size, stamp, name = match.groups()
        try:
            modified = datetime.strptime(stamp, "%d %b %Y %H:%M:%S")
        except ValueError:
            modified = None
        entries.append(RemoteEntry(name, kind == "d", int(size), modified))
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.casefold()))


def child_path(folder: str, name: str) -> str:
    if not name or "/" in name or name in (".", ".."):
        raise AfcError(f"Invalid name: {name!r}")
    return f"{folder.rstrip('/')}/{name}"


def parent_path(path: str) -> str:
    parent = path.rstrip("/").rsplit("/", 1)[0]
    return parent or "/"


def sharing_apps(data: bytes) -> list[SharingApp]:
    try:
        apps = plistlib.loads(data)
    except Exception:
        return []
    if not isinstance(apps, list):
        return []
    found = []
    for app in apps:
        if isinstance(app, dict) and app.get("UIFileSharingEnabled") is True and app.get("CFBundleIdentifier"):
            name = app.get("CFBundleDisplayName") or app.get("CFBundleName") or app["CFBundleIdentifier"]
            found.append(SharingApp(str(app["CFBundleIdentifier"]), str(name)))
    return sorted(found, key=lambda a: a.name.casefold())


_ICONS = {
    "image-x-generic-symbolic": {"jpg", "jpeg", "png", "heic", "heif", "gif", "webp", "tiff", "dng", "bmp"},
    "video-x-generic-symbolic": {"mov", "mp4", "m4v", "avi", "mkv", "webm", "3gp"},
    "audio-x-generic-symbolic": {"mp3", "m4a", "aac", "wav", "flac", "aiff", "caf", "ogg"},
}


def icon_for(name: str, is_dir: bool) -> str:
    if is_dir:
        return "folder-symbolic"
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for icon, extensions in _ICONS.items():
        if extension in extensions:
            return icon
    return "text-x-generic-symbolic"


def media_kind(name: str, is_dir: bool) -> str | None:
    icon = icon_for(name, is_dir)
    return icon.split("-", 1)[0] if icon in _ICONS else None
