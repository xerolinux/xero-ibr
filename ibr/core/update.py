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
    sha256: str


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text or ""))


def newer(candidate: str, current: str) -> bool:
    return _version(candidate) > _version(current)


def latest_version(final_url: str) -> str | None:
    """Version from where github.com/<repo>/releases/latest redirects, which needs no rate-limited API call."""
    match = re.search(r"/releases/tag/v?(\d+(?:\.\d+)*)$", final_url)
    return match[1] if match else None


def asset_url(repo: str, version: str, arch: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/iBR-{version}-{arch}.AppImage"


def parse_checksum(text: str, name: str) -> str | None:
    """The digest for name from sha256sum output."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
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
