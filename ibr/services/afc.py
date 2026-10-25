import ctypes
from pathlib import Path

from ..core.afc import AfcError, SharingApp, check_output, child_path, parse_listing, sharing_apps
from .runner import run

_VOID_P = ctypes.c_void_p


def load_library(*names: str) -> ctypes.CDLL:
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise AfcError(f"Cannot load {names[0]}")


def list_sharing_apps(udid: str) -> list[SharingApp]:
    """Blocking: asks installation_proxy for user apps that enable iTunes-style File Sharing."""
    imd = load_library("libimobiledevice-1.0.so.6", "libimobiledevice-1.0.so")
    plist = load_library("libplist-2.0.so.4", "libplist-2.0.so")
    for name, args in (
        ("idevice_new", [ctypes.POINTER(_VOID_P), ctypes.c_char_p]),
        ("idevice_free", [_VOID_P]),
        ("instproxy_client_start_service", [_VOID_P, ctypes.POINTER(_VOID_P), ctypes.c_char_p]),
        ("instproxy_browse", [_VOID_P, _VOID_P, ctypes.POINTER(_VOID_P)]),
        ("instproxy_client_free", [_VOID_P]),
    ):
        getattr(imd, name).argtypes = args
        getattr(imd, name).restype = ctypes.c_int
    plist.plist_new_dict.restype = _VOID_P
    plist.plist_new_array.restype = _VOID_P
    plist.plist_new_string.restype = _VOID_P
    plist.plist_new_string.argtypes = [ctypes.c_char_p]
    plist.plist_dict_set_item.argtypes = [_VOID_P, ctypes.c_char_p, _VOID_P]
    plist.plist_array_append_item.argtypes = [_VOID_P, _VOID_P]
    plist.plist_to_xml.argtypes = [_VOID_P, ctypes.POINTER(_VOID_P), ctypes.POINTER(ctypes.c_uint32)]
    plist.plist_free.argtypes = [_VOID_P]
    plist.plist_mem_free.argtypes = [_VOID_P]

    device, client, result = _VOID_P(), _VOID_P(), _VOID_P()
    options = plist.plist_new_dict()
    try:
        plist.plist_dict_set_item(options, b"ApplicationType", plist.plist_new_string(b"User"))
        attributes = plist.plist_new_array()
        for key in (b"CFBundleIdentifier", b"CFBundleDisplayName", b"CFBundleName", b"UIFileSharingEnabled"):
            plist.plist_array_append_item(attributes, plist.plist_new_string(key))
        plist.plist_dict_set_item(options, b"ReturnAttributes", attributes)
        if imd.idevice_new(ctypes.byref(device), udid.encode()) != 0:
            raise AfcError("Device not found")
        if imd.instproxy_client_start_service(device, ctypes.byref(client), b"ibr") != 0:
            raise AfcError("Could not reach the app list on the device")
        if imd.instproxy_browse(client, options, ctypes.byref(result)) != 0 or not result:
            raise AfcError("Could not read the app list")
        xml, length = _VOID_P(), ctypes.c_uint32()
        plist.plist_to_xml(result, ctypes.byref(xml), ctypes.byref(length))
        try:
            data = ctypes.string_at(xml, length.value)
        finally:
            plist.plist_mem_free(xml)
        return sharing_apps(data)
    finally:
        if result:
            plist.plist_free(result)
        plist.plist_free(options)
        if client:
            imd.instproxy_client_free(client)
        if device:
            imd.idevice_free(device)


class Afc:
    """afcclient wrapper. app_id switches from the Media area to that app's shared Documents."""

    def __init__(self, udid: str, app_id: str | None = None):
        self.udid = udid
        self.app_id = app_id

    def _argv(self, *command: str) -> list[str]:
        scope = ["--documents", self.app_id] if self.app_id else []
        return ["afcclient", "-u", self.udid, *scope, "--", *command]

    def _call(self, callback, parse, *command: str):
        def done(status, out, err):
            text = out.decode(errors="replace") + err.decode(errors="replace")
            try:
                if status != 0:
                    lines = [line for line in text.splitlines() if line.strip()]
                    raise AfcError(lines[0] if lines else f"afcclient exited with status {status}")
                callback(parse(text), None)
            except AfcError as error:
                callback(None, str(error))

        run(self._argv(*command), done)

    def list(self, path: str, callback):
        self._call(callback, parse_listing, "ls", "-l", path)

    def mkdir(self, path: str, callback):
        self._call(callback, check_output, "mkdir", path)

    def remove(self, paths: list[str], callback):
        self._call(callback, check_output, "rm", "-rf", "--", *paths)

    def rename(self, old: str, new: str, callback):
        self._call(callback, check_output, "mv", old, new)

    def download(self, remote: str, local_dir: Path, callback):
        target = Path(local_dir) / remote.rstrip("/").rsplit("/", 1)[-1]
        self._call(lambda result, error: callback(target if error is None else None, error),
                   check_output, "get", "-rf", "--", remote, str(target))

    def upload(self, local: Path, remote_dir: str, callback):
        self._call(callback, check_output, "put", "-rf", "--", str(local), child_path(remote_dir, Path(local).name))
