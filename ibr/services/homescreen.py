import ctypes
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..core.app_catalog import AppMeta, catalog_file, load_saved, save_merged, visible_apps
from ..core.homescreen import HomeIcon, parse_icon_state
from .afc import browse_apps, load_library

_VP = ctypes.c_void_p
APP_LIMIT = 30
FOLDER_PREVIEW = 4


@dataclass
class HomeScreenImage:
    wallpaper: bytes | None = None
    dock: list[tuple[HomeIcon, list[bytes]]] = field(default_factory=list)
    apps: list[tuple[HomeIcon, list[bytes]]] = field(default_factory=list)


class _SpringBoard:
    def __init__(self, imd, plist, client):
        self._imd, self._plist, self._client = imd, plist, client

    def _png(self, call, *args) -> bytes | None:
        data, size = _VP(), ctypes.c_uint64()
        if call(self._client, *args, ctypes.byref(data), ctypes.byref(size)) != 0 or not data:
            return None
        try:
            return ctypes.string_at(data, size.value)
        finally:
            self._plist.plist_mem_free(data)

    def wallpaper(self) -> bytes | None:
        return self._png(self._imd.sbservices_get_home_screen_wallpaper_pngdata)

    def icon(self, bundle_id: str) -> bytes | None:
        return self._png(self._imd.sbservices_get_icon_pngdata, bundle_id.encode())

    def icon_state(self) -> bytes | None:
        state = _VP()
        if self._imd.sbservices_get_icon_state(self._client, ctypes.byref(state), b"2") != 0 or not state:
            return None
        xml, length = _VP(), ctypes.c_uint32()
        self._plist.plist_to_xml(state, ctypes.byref(xml), ctypes.byref(length))
        try:
            return ctypes.string_at(xml, length.value)
        finally:
            self._plist.plist_mem_free(xml)
            self._plist.plist_free(state)


@contextmanager
def _springboard(udid: str):
    """Yields a SpringBoard services session, or None when the device or library is unavailable."""
    try:
        imd = load_library("libimobiledevice-1.0.so.6", "libimobiledevice-1.0.so")
        plist = load_library("libplist-2.0.so.4", "libplist-2.0.so")
    except Exception:
        yield None
        return
    imd.idevice_new.argtypes = [ctypes.POINTER(_VP), ctypes.c_char_p]
    imd.idevice_free.argtypes = [_VP]
    imd.sbservices_client_start_service.argtypes = [_VP, ctypes.POINTER(_VP), ctypes.c_char_p]
    imd.sbservices_client_free.argtypes = [_VP]
    imd.sbservices_get_home_screen_wallpaper_pngdata.argtypes = [_VP, ctypes.POINTER(_VP),
                                                                 ctypes.POINTER(ctypes.c_uint64)]
    imd.sbservices_get_icon_state.argtypes = [_VP, ctypes.POINTER(_VP), ctypes.c_char_p]
    imd.sbservices_get_icon_pngdata.argtypes = [_VP, ctypes.c_char_p, ctypes.POINTER(_VP),
                                                ctypes.POINTER(ctypes.c_uint64)]
    plist.plist_to_xml.argtypes = [_VP, ctypes.POINTER(_VP), ctypes.POINTER(ctypes.c_uint32)]
    plist.plist_free.argtypes = [_VP]
    plist.plist_mem_free.argtypes = [_VP]

    device, client = _VP(), _VP()
    try:
        if imd.idevice_new(ctypes.byref(device), udid.encode()) != 0:
            yield None
        elif imd.sbservices_client_start_service(device, ctypes.byref(client), b"ibr") != 0:
            yield None
        else:
            yield _SpringBoard(imd, plist, client)
    finally:
        if client:
            imd.sbservices_client_free(client)
        if device:
            imd.idevice_free(device)


def fetch_home(udid: str) -> HomeScreenImage | None:
    """Blocking: the device's wallpaper, dock and Home Screen apps (in order) with their icons, from SpringBoard."""
    with _springboard(udid) as board:
        if board is None:
            return None
        image = HomeScreenImage(wallpaper=board.wallpaper())
        state = board.icon_state()
        if state is None:
            return image
        home = parse_icon_state(state)

        def icons(entries: list[HomeIcon]):
            result = []
            for icon in entries:
                ids = [icon.bundle_id] if icon.bundle_id else icon.folder[:FOLDER_PREVIEW]
                result.append((icon, [p for p in map(board.icon, ids) if p]))
            return result

        image.dock = icons(home.dock)
        image.apps = icons(home.apps[:APP_LIMIT])
        return image


def refresh_app_catalog(udid: str) -> bool:
    """Blocking: saves the name and icon of every app on the device, so backups can show Apple's own apps.
    The device's icons replace App Store artwork saved earlier. Returns True when something changed."""
    try:
        names = visible_apps(browse_apps(udid, "Any"))
    except Exception:
        names = {}
    with _springboard(udid) as board:
        if board is None:
            return False
        state = board.icon_state()
        if state:
            names.update(parse_icon_state(state).names)
        path = catalog_file(udid)
        saved = load_saved(path)
        found = {}
        for bid, name in names.items():
            known = saved.get(bid)
            meta = AppMeta(name, board.icon(bid) or (known.icon if known else None))
            if meta != known:
                found[bid] = meta
    if not found:
        return False
    try:
        save_merged(path, found)
    except OSError:
        return False
    return True
