import os
import plistlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .snapshots import DAMAGED_MARKER, SNAPSHOT_DIR, stamps


@dataclass(frozen=True)
class BackupEntry:
    udid: str
    path: Path
    device_name: str
    product_type: str
    os_version: str
    date: datetime | None
    encrypted: bool
    complete: bool
    restore_root: Path
    damaged: bool = False

    @property
    def local_date(self) -> datetime | None:
        if self.date is None:
            return None
        return self.date.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _read(path: Path) -> dict | None:
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _entry(folder: Path, restore_root: Path) -> BackupEntry | None:
    info = _read(folder / "Info.plist")
    if info is None:
        return None
    manifest = _read(folder / "Manifest.plist") or {}
    status = _read(folder / "Status.plist") or {}
    date = info.get("Last Backup Date")
    return BackupEntry(
        udid=folder.name,
        path=folder,
        device_name=str(info.get("Device Name", folder.name)),
        product_type=str(info.get("Product Type", "")),
        os_version=str(info.get("Product Version", "")),
        date=date if isinstance(date, datetime) else None,
        encrypted=manifest.get("IsEncrypted") is True,
        complete=status.get("SnapshotState") == "finished",
        restore_root=restore_root,
        damaged=(restore_root / DAMAGED_MARKER).exists(),
    )


def _dirs(path: Path) -> list[Path]:
    try:
        return [p for p in path.iterdir() if p.is_dir()]
    except OSError:
        return []


def scan_backups(root: Path) -> list[BackupEntry]:
    root = Path(root)
    entries = []
    snapshots = root / SNAPSHOT_DIR
    udids = {p.name for p in _dirs(root) if p.name != SNAPSHOT_DIR} | {p.name for p in _dirs(snapshots)}
    for udid in udids:
        history = [e for e in (_entry(stamp / udid, stamp) for stamp in stamps(root, udid)) if e is not None]
        entries.extend(history)
        live = _entry(root / udid, root)
        newest = max((e.date for e in history if e.date), default=None)
        if live and (not history or (live.date and (newest is None or live.date > newest))):
            entries.append(live)
    dated = sorted((e for e in entries if e.date), key=lambda e: e.date, reverse=True)
    return dated + [e for e in entries if not e.date]


def dir_size(path: Path) -> int:
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total
