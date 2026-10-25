import re

from .backups import BackupEntry
from .catalog import lookup
from .deviceinfo import DeviceInfo


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text or "")[:3])


def restore_problem(entry: BackupEntry, device: DeviceInfo) -> str | None:
    if entry.damaged:
        return "Damaged by a later backup"
    if not entry.complete:
        return "Incomplete backup"
    source_kind = lookup(entry.product_type).kind if entry.product_type else device.spec.kind
    if source_kind != device.spec.kind:
        return f"Backup is from an {'iPad' if source_kind == 'ipad' else 'iPhone'}"
    if entry.os_version and _version(entry.os_version) > _version(device.os_version):
        return f"Made on {entry.os_version}; update this device first"
    return None


def problem_detail(entry: BackupEntry, device: DeviceInfo) -> str | None:
    problem = restore_problem(entry, device)
    if problem is None:
        return None
    if problem.startswith("Made on"):
        return (f"This backup was made on iOS {entry.os_version}, but {device.name} runs {device.os_label}. "
                "A backup can only be restored to a device running the same or a newer version. Update the "
                "device in Settings > General > Software Update, then try again.")
    if problem.startswith("Backup is from"):
        return "Backups from an iPad cannot be restored to an iPhone, and iPhone backups cannot go to an iPad."
    if problem == "Damaged by a later backup":
        return ("A later backup overwrote part of this one, so it cannot be restored safely. "
                "Choose a newer backup.")
    return "This backup did not finish, so it cannot be restored. Choose another backup or back up again."
