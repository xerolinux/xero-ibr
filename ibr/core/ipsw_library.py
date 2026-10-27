import plistlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .firmware import build_order

_MODELS = re.compile(r"(?:iPhone|iPad|iPod)\d+,\d+")
_NAME = re.compile(r"_(\d+(?:\.\d+)+)_(\d+[A-Z]\d+[a-z]?)_")


@dataclass(frozen=True)
class IpswInfo:
    path: str
    version: str
    build: str
    models: tuple[str, ...]
    size: int


def read_ipsw(path: Path) -> IpswInfo:
    """Version, build and supported models from the file's BuildManifest, else from Apple's file name."""
    path = Path(path)
    size = path.stat().st_size
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = plistlib.loads(archive.read("BuildManifest.plist"))
        models = tuple(str(m) for m in manifest.get("SupportedProductTypes") or ())
        return IpswInfo(str(path), str(manifest.get("ProductVersion", "")),
                        str(manifest.get("ProductBuildVersion", "")), models, size)
    except (zipfile.BadZipFile, KeyError, OSError, plistlib.InvalidFileException, ValueError, AttributeError):
        named = _NAME.search(path.name)
        return IpswInfo(str(path), named[1] if named else "", named[2] if named else "",
                        tuple(_MODELS.findall(path.name)), size)


def _newest(info: IpswInfo) -> tuple:
    return tuple(int(p) for p in info.version.split(".") if p.isdigit()), build_order(info.build)


def scan_folder(folder: Path) -> list[IpswInfo]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob("*.ipsw"):
        try:
            found.append(read_ipsw(path))
        except OSError:
            continue
    return sorted(found, key=_newest, reverse=True)


def ipsw_state(info: IpswInfo, product_type: str, signed: set[str] | None) -> str:
    """fits, unsigned (for this device but Apple no longer signs it), other (another device) or unknown.
    signed is None while Apple's list is not known yet."""
    if not info.models:
        return "unknown"
    if product_type not in info.models:
        return "other"
    return "unsigned" if signed is not None and info.build not in signed else "fits"


def best_for(files: list[IpswInfo], product_type: str, signed: set[str] | None) -> IpswInfo | None:
    """The newest signed file for the device, else the newest file for it."""
    usable = [f for f in files if product_type in f.models]
    return next((f for f in usable if signed is None or f.build in signed), usable[0] if usable else None)
