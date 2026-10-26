import io
import json
import math
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path

import cairo

from .settings import xdg_dir

_ARTWORK_SIZE = re.compile(r"/\d+x\d+bb\.\w+$")


@dataclass(frozen=True)
class AppMeta:
    name: str
    icon: bytes | None


# Apple's own apps are not listed in a backup's Info.plist. Extra ids are their shared group names.
APPLE_APPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "com.apple.AppStore": ("App Store", ()),
    "com.apple.Bridge": ("Watch", ()),
    "com.apple.DocumentsApp": ("Files", ("com.apple.DocumentManager", "com.apple.FileProvider.LocalStorage")),
    "com.apple.Fitness": ("Fitness", ()),
    "com.apple.Health": ("Health", ()),
    "com.apple.Home": ("Home", ("com.apple.Home.group",)),
    "com.apple.Keynote": ("Keynote", ()),
    "com.apple.Magnifier": ("Magnifier", ()),
    "com.apple.Maps": ("Maps", ()),
    "com.apple.MobileAddressBook": ("Contacts", ("com.apple.contacts",)),
    "com.apple.MobileSMS": ("Messages", ()),
    "com.apple.Music": ("Music", ("com.apple.musicd",)),
    "com.apple.Numbers": ("Numbers", ()),
    "com.apple.Pages": ("Pages", ()),
    "com.apple.Passbook": ("Wallet", ()),
    "com.apple.Passwords": ("Passwords", ()),
    "com.apple.Preferences": ("Settings", ()),
    "com.apple.TVRemoteApp": ("Apple TV Remote", ("com.apple.TVRemote",)),
    "com.apple.TestFlight": ("TestFlight", ("com.apple.testflight",)),
    "com.apple.VoiceMemos": ("Voice Memos", ()),
    "com.apple.appleseed.FeedbackAssistant": ("Feedback", ("com.apple.feedback",)),
    "com.apple.calculator": ("Calculator", ()),
    "com.apple.camera": ("Camera", ()),
    "com.apple.clips": ("Clips", ()),
    "com.apple.compass": ("Compass", ()),
    "com.apple.facetime": ("FaceTime", ("com.apple.FaceTime",)),
    "com.apple.findmy": ("Find My", ("com.apple.icloud.fm",)),
    "com.apple.freeform": ("Freeform", ()),
    "com.apple.games": ("Games", ()),
    "com.apple.iBooks": ("Books", ()),
    "com.apple.iMovie": ("iMovie", ()),
    "com.apple.journal": ("Journal", ()),
    "com.apple.measure": ("Measure", ()),
    "com.apple.mobilecal": ("Calendar", ()),
    "com.apple.mobilegarageband": ("GarageBand", ()),
    "com.apple.mobilemail": ("Mail", ("com.apple.mail", "com.apple.MailPersonaStorage")),
    "com.apple.mobilenotes": ("Notes", ("com.apple.notes",)),
    "com.apple.mobilephone": ("Phone", ()),
    "com.apple.mobilesafari": ("Safari", ("com.apple.safari",)),
    "com.apple.mobileslideshow": ("Photos", ()),
    "com.apple.mobiletimer": ("Clock", ()),
    "com.apple.musicrecognition": ("Music Recognition", ()),
    "com.apple.news": ("News", ("com.apple.newsd",)),
    "com.apple.podcasts": ("Podcasts", ()),
    "com.apple.reminders": ("Reminders", ()),
    "com.apple.shortcuts": ("Shortcuts", ("is.workflow.my.app", "is.workflow.shortcuts")),
    "com.apple.sports": ("Sports", ()),
    "com.apple.stocks": ("Stocks", ("com.apple.stocks-news",)),
    "com.apple.tips": ("Tips", ("com.apple.tipsnext",)),
    "com.apple.tv": ("TV", ()),
    "com.apple.weather": ("Weather", ()),
}


def catalog_file(udid: str) -> Path:
    return xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "apps" / f"{udid}.plist"


def load_saved(path: Path) -> dict[str, AppMeta]:
    try:
        data = plistlib.loads(Path(path).read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {bid: AppMeta(str(entry.get("name", bid)), entry.get("icon"))
            for bid, entry in data.items() if isinstance(entry, dict)}


def save_merged(path: Path, entries: dict[str, AppMeta]):
    """Adds entries to the saved catalog; an icon already saved is kept when the new entry has none."""
    merged = load_saved(path)
    for bid, meta in entries.items():
        old = merged.get(bid)
        merged[bid] = AppMeta(meta.name, meta.icon or (old.icon if old else None))
    data = {bid: {"name": m.name, **({"icon": m.icon} if m.icon else {})} for bid, m in merged.items()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
    temp.replace(path)


def visible_apps(data: bytes) -> dict[str, str]:
    """Names of the apps an installation_proxy listing shows on the device, skipping hidden system services
    other than Apple apps that keep data in backups."""
    try:
        apps = plistlib.loads(data)
    except Exception:
        return {}
    found = {}
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict):
            continue
        if "hidden" in (app.get("SBAppTags") or []) and app.get("CFBundleIdentifier") not in APPLE_APPS:
            continue
        name = app.get("CFBundleDisplayName") or app.get("CFBundleName")
        if app.get("CFBundleIdentifier") and name:
            found[str(app["CFBundleIdentifier"])] = str(name)
    return found


def store_artwork(data: bytes) -> dict[str, str]:
    """Artwork links from an App Store lookup, asking for a 128 px PNG."""
    try:
        results = json.loads(data).get("results", [])
    except (ValueError, AttributeError):
        return {}
    found = {}
    for app in results:
        url = app.get("artworkUrl512") or app.get("artworkUrl100") if isinstance(app, dict) else None
        if url and app.get("bundleId") and _ARTWORK_SIZE.search(url):
            found[app["bundleId"]] = _ARTWORK_SIZE.sub("/128x128bb.png", url)
    return found


def rounded_icon(png: bytes) -> bytes:
    """Store artwork is square; iOS draws icons with rounded corners."""
    source = cairo.ImageSurface.create_from_png(io.BytesIO(png))
    size = 128
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    context = cairo.Context(surface)
    radius = size * 0.225
    context.new_sub_path()
    for x, y, start in ((size - radius, radius, -0.5), (size - radius, size - radius, 0),
                        (radius, size - radius, 0.5), (radius, radius, 1)):
        context.arc(x, y, radius, start * math.pi, (start + 0.5) * math.pi)
    context.close_path()
    context.clip()
    context.scale(size / source.get_width(), size / source.get_height())
    context.set_source_surface(source)
    context.paint()
    out = io.BytesIO()
    surface.write_to_png(out)
    return out.getvalue()
