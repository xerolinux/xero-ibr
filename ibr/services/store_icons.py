import urllib.parse
import urllib.request

import cairo

from .. import __version__
from ..core.app_catalog import rounded_icon, store_artwork

_HEADERS = {"User-Agent": f"iBR/{__version__}"}
_BATCH = 100


def fetch_store_icons(bundle_ids: list[str]) -> dict[str, bytes]:
    """Blocking: icons for apps the backup has none for, from Apple's public App Store lookup."""
    icons = {}
    for start in range(0, len(bundle_ids), _BATCH):
        query = urllib.parse.urlencode({"bundleId": ",".join(bundle_ids[start:start + _BATCH])})
        try:
            request = urllib.request.Request(f"https://itunes.apple.com/lookup?{query}", headers=_HEADERS)
            with urllib.request.urlopen(request, timeout=20) as response:
                artwork = store_artwork(response.read())
        except OSError:
            continue
        for bundle_id, url in artwork.items():
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=20) as response:
                    icons[bundle_id] = rounded_icon(response.read())
            except (OSError, cairo.Error):
                continue
    return icons
