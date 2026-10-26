import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

APPLE_VENDOR = "05ac"
# USB product IDs Apple devices use outside normal mode (from libirecovery).
RECOVERY_PIDS = {
    "1222": "WTF",
    "1227": "DFU",
    "1280": "Recovery",
    "1281": "Recovery",
    "1282": "Recovery",
    "1283": "Recovery",
    "1881": "DFU",
    "f014": "DFU",
}
# Power tools such as TLP switch USB devices to autosuspend from their own RUN rule, which can drop a long
# backup. RUN (not ATTR) from a late file is applied after theirs.
UDEV_RULE = (f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{APPLE_VENDOR}", '
             f'ATTR{{idProduct}}=="{"|".join(RECOVERY_PIDS)}", TAG+="uaccess"\n'
             f'ACTION=="add", SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", ATTR{{idVendor}}=="{APPLE_VENDOR}", '
             f'TEST=="power/control", RUN+="/bin/sh -c \'echo on > /sys%p/power/control\'"\n')
UDEV_RULE_PATH = "/etc/udev/rules.d/99-ibr.rules"
OLD_UDEV_RULE_PATH = "/etc/udev/rules.d/70-ibr-recovery.rules"
INSTALLED_RULE_PATHS = (Path(UDEV_RULE_PATH), Path("/usr/lib/udev/rules.d/99-ibr.rules"))


def install_script() -> str:
    """Root shell script that installs the rule, replaces the old one and applies it to connected devices."""
    return (f"rm -f {OLD_UDEV_RULE_PATH} && printf '%s' {shlex.quote(UDEV_RULE)} > {UDEV_RULE_PATH} && "
            "udevadm control --reload-rules && udevadm trigger --subsystem-match=usb --attr-match=idVendor=05ac")


def manual_command() -> str:
    return f"sudo sh -c {shlex.quote(install_script())}"


def rule_installed(paths=INSTALLED_RULE_PATHS) -> bool:
    for path in paths:
        try:
            if Path(path).read_text() == UDEV_RULE:
                return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class UsbRecovery:
    mode: str
    ecid: str | None
    port: str


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def scan_usb(root: Path = Path("/sys/bus/usb/devices")) -> list[UsbRecovery]:
    try:
        folders = sorted(p for p in Path(root).iterdir() if p.is_dir())
    except OSError:
        return []
    found = []
    for folder in folders:
        if _read(folder / "idVendor").lower() != APPLE_VENDOR:
            continue
        mode = RECOVERY_PIDS.get(_read(folder / "idProduct").lower())
        if not mode:
            continue
        match = re.search(r"ECID:([0-9A-Fa-f]+)", _read(folder / "serial"))
        ecid = "0x" + (match.group(1).lstrip("0").upper() or "0") if match else None
        found.append(UsbRecovery(mode, ecid, folder.name))
    return found


def parse_irecovery(text: str) -> dict:
    keys = {"MODE": "mode", "PRODUCT": "product_type", "NAME": "name", "ECID": "ecid"}
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition(": ")
        if key in keys and value.strip():
            found[keys[key]] = value.strip()
    return found


_INSTALL = (
    ({"arch", "artix"}, "sudo pacman -S usbmuxd"),
    ({"debian", "ubuntu"}, "sudo apt install usbmuxd"),
    ({"fedora", "rhel", "centos"}, "sudo dnf install usbmuxd"),
    ({"opensuse", "suse"}, "sudo zypper install usbmuxd"),
    ({"void"}, "sudo xbps-install usbmuxd"),
    ({"alpine"}, "sudo apk add usbmuxd"),
    ({"gentoo"}, "sudo emerge app-pda/usbmuxd"),
    ({"nixos"}, "services.usbmuxd.enable = true;"),
)


def usbmuxd_install_hint(os_release: str) -> str:
    values = {}
    for line in os_release.splitlines():
        key, _, value = line.partition("=")
        values[key] = value.strip().strip('"')
    families = {values.get("ID", "")} | set(values.get("ID_LIKE", "").split())
    families |= {family.split("-")[0] for family in families}
    for names, command in _INSTALL:
        if families & names:
            return command
    return "Install the usbmuxd package from your distribution."


def clean_transfers(folder: Path):
    try:
        children = list(Path(folder).iterdir())
    except OSError:
        return
    for child in children:
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
