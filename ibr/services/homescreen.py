import ctypes
from dataclasses import dataclass, field

from ..core.homescreen import HomeIcon, parse_icon_state
from .afc import load_library

_VP = ctypes.c_void_p
APP_LIMIT = 30
FOLDER_PREVIEW = 4


@dataclass
class HomeScreenImage:
    wallpaper: bytes | None = None
    dock: list[tuple[HomeIcon, list[bytes]]] = field(default_factory=list)
    apps: list[tuple[HomeIcon, list[bytes]]] = field(default_factory=list)


def fetch_home(udid: str) -> HomeScreenImage | None:
    """Blocking: the device's wallpaper, dock and Home Screen apps (in order) with their icons, from SpringBoard."""
    try:
        imd = load_library("libimobiledevice-1.0.so.6", "libimobiledevice-1.0.so")
        plist = load_library("libplist-2.0.so.4", "libplist-2.0.so")
    except Exception:
        return None
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
            return None
        if imd.sbservices_client_start_service(device, ctypes.byref(client), b"ibr") != 0:
            return None

        def png(call, *args) -> bytes | None:
            data, size = _VP(), ctypes.c_uint64()
            if call(client, *args, ctypes.byref(data), ctypes.byref(size)) != 0 or not data:
                return None
            try:
                return ctypes.string_at(data, size.value)
            finally:
                plist.plist_mem_free(data)

        image = HomeScreenImage(wallpaper=png(imd.sbservices_get_home_screen_wallpaper_pngdata))
        state = _VP()
        if imd.sbservices_get_icon_state(client, ctypes.byref(state), b"2") != 0 or not state:
            return image
        xml, length = _VP(), ctypes.c_uint32()
        plist.plist_to_xml(state, ctypes.byref(xml), ctypes.byref(length))
        home = parse_icon_state(ctypes.string_at(xml, length.value))
        plist.plist_mem_free(xml)
        plist.plist_free(state)

        def icons(entries: list[HomeIcon]):
            result = []
            for icon in entries:
                ids = [icon.bundle_id] if icon.bundle_id else icon.folder[:FOLDER_PREVIEW]
                result.append((icon, [p for p in (png(imd.sbservices_get_icon_pngdata, b.encode()) for b in ids) if p]))
            return result

        image.dock = icons(home.dock)
        image.apps = icons(home.apps[:APP_LIMIT])
        return image
    finally:
        if client:
            imd.sbservices_client_free(client)
        if device:
            imd.idevice_free(device)
