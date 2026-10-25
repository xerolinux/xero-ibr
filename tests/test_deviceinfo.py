import plistlib

from ibr.core.deviceinfo import parse_device_info

INFO = plistlib.dumps({
    "UniqueDeviceID": "00008120-001A2B3C4D5E6F70",
    "DeviceName": "My iPhone",
    "ProductType": "iPhone17,1",
    "ProductVersion": "26.0.1",
    "BuildVersion": "23A355",
    "SerialNumber": "F2LXXXXXXQ7",
    "ModelNumber": "MYNF3",
    "RegionInfo": "B/A",
    "DeviceClass": "iPhone",
    "DeviceEnclosureColor": "2",
})
BATTERY = plistlib.dumps({"BatteryCurrentCapacity": 87, "BatteryIsCharging": True})
DISK = plistlib.dumps({
    "TotalDiskCapacity": 256_000_000_000,
    "TotalDataCapacity": 245_000_000_000,
    "TotalDataAvailable": 108_000_000_000,
    "TotalSystemCapacity": 8_000_000_000,
})
BACKUP = plistlib.dumps({"WillEncrypt": True})


def test_full_parse():
    info = parse_device_info(INFO, BATTERY, DISK, BACKUP)
    assert info.udid == "00008120-001A2B3C4D5E6F70"
    assert info.name == "My iPhone"
    assert info.product_type == "iPhone17,1"
    assert info.os_version == "26.0.1"
    assert info.build == "23A355"
    assert info.model_number == "MYNF3B/A"
    assert info.spec.name == "iPhone 16 Pro"
    assert info.finish == info.spec.finish
    assert info.battery_level == 87
    assert info.charging is True
    assert info.total_bytes == 256_000_000_000
    assert info.used_bytes == 148_000_000_000
    assert info.system_bytes == 8_000_000_000
    assert info.will_encrypt is True


def test_optional_domains_missing():
    info = parse_device_info(INFO, None, None, None)
    assert info.battery_level is None
    assert info.charging is None
    assert info.total_bytes is None
    assert info.used_bytes is None
    assert info.will_encrypt is None


def test_garbage_optional_domain_is_ignored():
    info = parse_device_info(INFO, b"not a plist", b"", None)
    assert info.battery_level is None
    assert info.total_bytes is None


def test_os_label_for_ipad():
    ipad = plistlib.dumps({
        "UniqueDeviceID": "x", "DeviceName": "Studio iPad", "ProductType": "iPad16,5",
        "ProductVersion": "26.0", "DeviceClass": "iPad",
    })
    info = parse_device_info(ipad, None, None, None)
    assert info.os_label == "iPadOS 26.0"


def test_os_label_for_iphone():
    assert parse_device_info(INFO, None, None, None).os_label == "iOS 26.0.1"
