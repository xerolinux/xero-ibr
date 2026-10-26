import re
from pathlib import Path

from .recovery import APPLE_VENDOR, _read

_SBIN = ("/usr/sbin/usbmuxd", "/sbin/usbmuxd", "/usr/bin/usbmuxd")
# Product IDs usbmuxd claims (from its own udev rule): normal-mode iPhone/iPad/iPod and T2 Macs.
_MUXABLE = re.compile(r"12[9a][0-9a-f]|8600")


def find_usbmuxd(which, exists) -> str | None:
    """Debian-based systems keep usbmuxd in /usr/sbin, which is not on a normal user's PATH."""
    return which("usbmuxd") or next((path for path in _SBIN if exists(path)), None)


def has_systemd(root: Path = Path("/")) -> bool:
    return (Path(root) / "run" / "systemd" / "system").is_dir()


def start_command(systemd: bool, binary: str) -> list[str]:
    """Without systemd, udev starts usbmuxd on plug-in; this starts it by hand, exiting like the udev one does."""
    if systemd:
        return ["systemctl", "start", "usbmuxd.service"]
    return [binary, "--user", "usbmux", "--enable-exit"]


def status_tip(systemd: bool) -> str:
    if systemd:
        return "Check the service with: systemctl status usbmuxd"
    return "usbmuxd is started by udev when the device is plugged in. If it is not found, reconnect the cable."


def muxable_device_present(root: Path = Path("/sys/bus/usb/devices")) -> bool:
    """An iPhone or iPad in normal mode is on USB, so usbmuxd should be answering."""
    try:
        folders = [p for p in Path(root).iterdir() if p.is_dir()]
    except OSError:
        return False
    return any(_read(folder / "idVendor").lower() == APPLE_VENDOR
               and _MUXABLE.fullmatch(_read(folder / "idProduct").lower()) for folder in folders)
