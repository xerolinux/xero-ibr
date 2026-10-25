import plistlib
from dataclasses import dataclass

from .catalog import ModelSpec, lookup, resolve_finish


def _load(data: bytes | None) -> dict:
    if not data:
        return {}
    try:
        value = plistlib.loads(data)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class DeviceInfo:
    udid: str
    name: str
    product_type: str
    os_version: str
    serial: str
    model_number: str
    device_class: str
    enclosure_color: str | None
    battery_level: int | None
    charging: bool | None
    total_bytes: int | None
    available_bytes: int | None
    will_encrypt: bool | None

    @property
    def spec(self) -> ModelSpec:
        return lookup(self.product_type, self.device_class)

    @property
    def finish(self) -> str:
        return resolve_finish(self.spec, self.enclosure_color)

    @property
    def used_bytes(self) -> int | None:
        if self.total_bytes is None or self.available_bytes is None:
            return None
        return self.total_bytes - self.available_bytes

    @property
    def os_label(self) -> str:
        prefix = "iPadOS" if self.spec.kind == "ipad" else "iOS"
        return f"{prefix} {self.os_version}"


def parse_device_info(info: bytes, battery: bytes | None, disk: bytes | None,
                      backup: bytes | None) -> DeviceInfo:
    base = _load(info)
    power = _load(battery)
    storage = _load(disk)
    backup_domain = _load(backup)
    level = power.get("BatteryCurrentCapacity")
    charging = power.get("BatteryIsCharging")
    total = storage.get("TotalDiskCapacity")
    available = storage.get("TotalDataAvailable")
    will_encrypt = backup_domain.get("WillEncrypt")
    return DeviceInfo(
        udid=str(base.get("UniqueDeviceID", "")),
        name=str(base.get("DeviceName", "")),
        product_type=str(base.get("ProductType", "")),
        os_version=str(base.get("ProductVersion", "")),
        serial=str(base.get("SerialNumber", "")),
        model_number=f"{base.get('ModelNumber', '')}{base.get('RegionInfo', '')}",
        device_class=str(base.get("DeviceClass", "")),
        enclosure_color=base.get("DeviceEnclosureColor"),
        battery_level=level if isinstance(level, int) else None,
        charging=charging if isinstance(charging, bool) else None,
        total_bytes=total if isinstance(total, int) else None,
        available_bytes=available if isinstance(available, int) else None,
        will_encrypt=will_encrypt if isinstance(will_encrypt, bool) else None,
    )
