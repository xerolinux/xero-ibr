from dataclasses import dataclass

from gi.repository import GLib, GObject

from ..core.deviceinfo import DeviceInfo, parse_device_info
from ..core.recovery import parse_irecovery, scan_usb
from .runner import run

_INFO_DOMAINS = (None, "com.apple.mobile.battery", "com.apple.disk_usage", "com.apple.mobile.backup")


@dataclass
class Device:
    udid: str
    state: str = "checking"
    info: DeviceInfo | None = None
    message: str = ""


@dataclass
class RecoveryDevice:
    key: str
    mode: str
    ecid: str | None
    product_type: str | None = None
    name: str | None = None
    queried: bool = False
    error: str = ""


def trust_message(output: str) -> str:
    text = output.lower()
    if "passcode" in text:
        return "Unlock your device with its passcode, then tap Trust."
    if "denied" in text or "rejected" in text:
        return "Trust was declined. Unplug the device and connect it again."
    return "Tap Trust on your device and enter its passcode."


class DeviceMonitor(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "scanning": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    POLL_SECONDS = 2

    def __init__(self):
        super().__init__()
        self.devices: dict[str, Device] = {}
        self.recovery: dict[str, RecoveryDevice] = {}
        self.usbmuxd_ok: bool | None = None
        self.paused = False
        self._busy = False
        self._quiet = False
        self._rescan = False
        self._pending = 0
        self._timer = 0

    def set_polling(self, enabled: bool):
        if enabled and not self._timer:
            self._timer = GLib.timeout_add_seconds(self.POLL_SECONDS, self._poll)
        elif not enabled and self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _poll(self):
        self.scan(refresh=False, quiet=True)
        return GLib.SOURCE_CONTINUE

    def scan(self, refresh: bool = True, quiet: bool = False):
        if self._busy:
            self._rescan = self._rescan or refresh
            return
        self._busy = True
        self._quiet = quiet
        if not quiet:
            self.emit("scanning", True)
        run(["idevice_id", "-l"], lambda status, out, err: self._on_list(status, out, refresh))

    def _on_list(self, status: int, out: bytes, refresh: bool):
        self.usbmuxd_ok = status == 0
        udids = list(dict.fromkeys(line.strip() for line in out.decode(errors="replace").splitlines() if line.strip()))
        changed = False
        for udid in list(self.devices):
            if udid not in udids:
                del self.devices[udid]
                changed = True
        to_check = []
        for udid in udids:
            device = self.devices.get(udid)
            if device is None:
                self.devices[udid] = Device(udid)
                changed = True
                to_check.append(udid)
            elif not self.paused and (refresh or device.state in ("checking", "trust", "error")):
                to_check.append(udid)
        if not self.paused and self._scan_recovery(refresh):
            changed = True
        if changed:
            self.emit("changed")
        self._pending = len(to_check)
        if not to_check:
            self._finish_scan()
        for udid in to_check:
            self._check(udid)

    def _scan_recovery(self, refresh: bool) -> bool:
        found = {(usb.ecid or usb.port): usb for usb in scan_usb()}
        changed = False
        for key in list(self.recovery):
            if key not in found:
                del self.recovery[key]
                changed = True
        for key, usb in found.items():
            device = self.recovery.get(key)
            if device is None or device.mode != usb.mode:
                device = self.recovery[key] = RecoveryDevice(key, usb.mode, usb.ecid)
                changed = True
            if refresh or not device.queried:
                self._query_recovery(device)
        return changed

    def _query_recovery(self, device: RecoveryDevice):
        device.queried = True

        def answered(status, out, err):
            current = self.recovery.get(device.key)
            if current is not device:
                return
            details = parse_irecovery(out.decode(errors="replace"))
            device.product_type = details.get("product_type", device.product_type)
            device.name = details.get("name", device.name)
            device.ecid = device.ecid or details.get("ecid")
            device.error = "" if details else (err or out).decode(errors="replace").strip() or "No response"
            self.emit("changed")

        run(["irecovery", "-q"] + (["-i", device.ecid] if device.ecid else []), answered)

    def exit_recovery(self, device: RecoveryDevice, callback):
        run(["irecovery"] + (["-i", device.ecid] if device.ecid else []) + ["-n"],
            lambda status, out, err: callback(status == 0, (err or out).decode(errors="replace").strip()))

    def _finish_scan(self):
        self._busy = False
        if not self._quiet:
            self.emit("scanning", False)
        if self._rescan:
            self._rescan = False
            self.scan(refresh=True, quiet=True)

    def _step_done(self):
        self._pending -= 1
        self.emit("changed")
        if self._pending <= 0:
            self._finish_scan()

    def _check(self, udid: str):
        def validated(status, out, err):
            if status == 0:
                self._fetch(udid)
            else:
                run(["idevicepair", "-u", udid, "pair"], paired)

        def paired(status, out, err):
            if status == 0:
                self._fetch(udid)
                return
            device = self.devices.get(udid)
            if device:
                device.state = "trust"
                device.message = trust_message((out + err).decode(errors="replace"))
            self._step_done()

        run(["idevicepair", "-u", udid, "validate"], validated)

    def _fetch(self, udid: str):
        results: list[bytes | None] = []

        def next_domain():
            domain = _INFO_DOMAINS[len(results)]
            argv = ["ideviceinfo", "-u", udid, "-x"] + (["-q", domain] if domain else [])
            run(argv, got)

        def got(status, out, err):
            results.append(out if status == 0 else None)
            if len(results) < len(_INFO_DOMAINS):
                next_domain()
                return
            device = self.devices.get(udid)
            if device:
                if results[0]:
                    device.info = parse_device_info(*results)
                    device.state = "ready"
                    device.message = ""
                else:
                    device.state = "error"
                    device.message = "Could not read device details. Unlock the device and scan again."
            self._step_done()

        next_domain()
