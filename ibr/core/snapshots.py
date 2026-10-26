import fcntl
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_DIR = "snapshots"
PARTIAL = ".partial"
DAMAGED_MARKER = ".damaged"
_FICLONE = 0x40049409


def snapshot_root(root: Path, udid: str) -> Path:
    return Path(root) / SNAPSHOT_DIR / udid


def stamps(root: Path, udid: str) -> list[Path]:
    try:
        found = [p for p in snapshot_root(root, udid).iterdir() if p.is_dir() and not p.name.endswith(PARTIAL)]
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name)


def new_stamp(root: Path, udid: str, when: datetime | None = None) -> str:
    base = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = snapshot_root(root, udid)
    stamp, counter = base, 0
    while (folder / stamp).exists() or (folder / f"{stamp}{PARTIAL}").exists():
        counter += 1
        stamp = f"{base}-{counter}"
    return stamp


def _clone(src: Path, dst: Path) -> bool:
    try:
        with open(src, "rb") as source, open(dst, "xb") as target:
            fcntl.ioctl(target.fileno(), _FICLONE, source.fileno())
    except OSError:
        try:
            os.unlink(dst)
        except OSError:
            pass
        return False
    shutil.copystat(src, dst)
    return True


def create_snapshot(root: Path, udid: str, stamp: str) -> Path:
    # Reflinks are copy-on-write. Hard links rely on idevicebackup2 unlinking files before rewriting
    # them; DLMessageCopyItem is the exception and is handled by mark_damaged().
    source = Path(root) / udid
    partial = snapshot_root(root, udid) / f"{stamp}{PARTIAL}"
    target = partial / udid
    reflink = None
    try:
        for folder, _, files in os.walk(source):
            rel = Path(folder).relative_to(source)
            (target / rel).mkdir(parents=True, exist_ok=True)
            for name in files:
                src, dst = Path(folder) / name, target / rel / name
                if reflink is not False:
                    reflink = _clone(src, dst)
                    if reflink:
                        continue
                os.link(src, dst)
        os.rename(partial, partial.with_name(stamp))
    except OSError:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return partial.with_name(stamp) / udid


def mark_damaged(root: Path, udid: str, copied: list[str]) -> list[Path]:
    live = Path(root) / udid
    damaged = []
    for stamp in stamps(root, udid):
        for rel in copied:
            try:
                shared = (stamp / udid / rel).stat().st_ino == (live / rel).stat().st_ino
            except OSError:
                continue
            if shared:
                (stamp / DAMAGED_MARKER).touch()
                damaged.append(stamp)
                break
    return damaged


def prune_snapshots(root: Path, udid: str, keep: int) -> list[Path]:
    base = snapshot_root(root, udid)
    try:
        for partial in base.glob(f"*{PARTIAL}"):
            shutil.rmtree(partial, ignore_errors=True)
    except OSError:
        return []
    removed = stamps(root, udid)[:-keep] if keep > 0 else stamps(root, udid)
    for path in removed:
        shutil.rmtree(path, ignore_errors=True)
    return removed


def delete_backup(root: Path, entry) -> None:
    root = Path(root)
    if Path(entry.restore_root) == root:
        shutil.rmtree(entry.path, ignore_errors=True)
        return
    names = [p.name for p in stamps(root, entry.udid)]
    container = Path(entry.restore_root)
    shutil.rmtree(container, ignore_errors=True)
    if names and container.name == names[-1]:
        shutil.rmtree(root / entry.udid, ignore_errors=True)
    base = snapshot_root(root, entry.udid)
    if base.is_dir() and not any(base.iterdir()):
        base.rmdir()


def finish_backup(root: Path, udid: str, copied: list[str], success: bool, keep: int, stamp: str) -> bool:
    """Snapshots a finished backup. A failed run can still have overwritten shared files in place, so marking
    damaged snapshots happens either way. Returns False when the snapshot could not be written."""
    mark_damaged(root, udid, copied)
    if not success:
        return True
    try:
        create_snapshot(root, udid, stamp)
    except OSError:
        return False
    prune_snapshots(root, udid, keep)
    return True
