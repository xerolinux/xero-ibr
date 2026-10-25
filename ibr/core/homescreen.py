import plistlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HomeIcon:
    name: str
    bundle_id: str | None
    folder: list[str] = field(default_factory=list)


@dataclass
class HomeScreen:
    dock: list[HomeIcon] = field(default_factory=list)
    apps: list[HomeIcon] = field(default_factory=list)


def _icon(item) -> HomeIcon | None:
    if not isinstance(item, dict):
        return None
    name = str(item.get("displayName", "")).strip("‎‏")
    if item.get("listType") == "folder":
        apps = [a.get("bundleIdentifier") for page in item.get("iconLists", []) for a in page
                if isinstance(a, dict) and a.get("bundleIdentifier")]
        return HomeIcon(name, None, apps)
    if item.get("bundleIdentifier"):
        return HomeIcon(name, str(item["bundleIdentifier"]))
    return None


def parse_icon_state(data: bytes) -> HomeScreen:
    """SpringBoard icon state: page 0 is the dock, the rest are Home Screen pages in order. Widgets are skipped."""
    try:
        pages = plistlib.loads(data)
    except Exception:
        return HomeScreen()
    if not isinstance(pages, list):
        return HomeScreen()
    icons = [[icon for icon in map(_icon, page) if icon] if isinstance(page, list) else [] for page in pages]
    return HomeScreen(icons[0] if icons else [], [icon for page in icons[1:] for icon in page])
