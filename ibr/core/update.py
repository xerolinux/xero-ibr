import json
import re
from dataclasses import dataclass

_RUNTIME_VARS = {"APPIMAGE", "APPDIR", "ARGV0", "OWD", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH",
                 "GI_TYPELIB_PATH", "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR", "GTK_PATH", "GTK_EXE_PREFIX",
                 "GTK_DATA_PREFIX", "GSETTINGS_SCHEMA_DIR", "GIO_MODULE_DIR", "GST_PLUGIN_PATH",
                 "GST_PLUGIN_SYSTEM_PATH", "GST_PLUGIN_SCANNER"}


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    size: int
    sha256: str | None


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text or ""))


def newer(candidate: str, current: str) -> bool:
    return _version(candidate) > _version(current)


def pick_update(data: bytes, arch: str, current: str) -> UpdateInfo | None:
    """Reads a GitHub "latest release" payload and returns the AppImage for this arch if it is newer."""
    try:
        release = json.loads(data)
    except ValueError:
        return None
    if not isinstance(release, dict):
        return None
    version = str(release.get("tag_name", "")).lstrip("v")
    if not version or not newer(version, current):
        return None
    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        if name.endswith(f"-{arch}.AppImage") and asset.get("browser_download_url"):
            digest = str(asset.get("digest") or "")
            return UpdateInfo(version, asset["browser_download_url"], int(asset.get("size") or 0),
                              digest.removeprefix("sha256:") if digest.startswith("sha256:") else None)
    return None


def clean_env(env: dict, mount: str) -> dict:
    """Environment for relaunching the new AppImage without leaking the running AppImage's mount paths."""
    cleaned = {}
    for key, value in env.items():
        if key in _RUNTIME_VARS or key.startswith("SHARUN_"):
            continue
        if key == "PATH":
            value = ":".join(p for p in value.split(":") if p and not p.startswith(mount))
        cleaned[key] = value
    return cleaned
