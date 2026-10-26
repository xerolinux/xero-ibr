import plistlib
from datetime import datetime

from ibr.core.backups import scan_backups
from ibr.core.compat import backup_warning, restore_problem
from ibr.core.deviceinfo import parse_device_info
from test_backups import make_backup


def device(product="iPhone17,1", version="26.0.1", klass="iPhone"):
    return parse_device_info(plistlib.dumps({
        "UniqueDeviceID": "DEV", "DeviceName": "Phone", "ProductType": product,
        "ProductVersion": version, "DeviceClass": klass,
    }), None, None, None)


def entry(tmp_path, **kwargs):
    make_backup(tmp_path, "SRC", "Phone", datetime(2026, 10, 1), **kwargs)
    return scan_backups(tmp_path)[0]


def test_ok(tmp_path):
    assert restore_problem(entry(tmp_path), device()) is None


def test_incomplete(tmp_path):
    assert restore_problem(entry(tmp_path, state="new"), device()) == "Incomplete backup"


def test_ipad_backup_to_iphone(tmp_path):
    problem = restore_problem(entry(tmp_path, product="iPad16,5"), device())
    assert problem == "Backup is from an iPad"


def test_newer_backup_than_device(tmp_path):
    problem = restore_problem(entry(tmp_path), device(version="18.6"))
    assert problem == "Made on 26.0.1; update this device first"


def test_version_compare_is_numeric(tmp_path):
    assert restore_problem(entry(tmp_path), device(version="26.0.10")) is None


def test_damaged_backup_blocked(tmp_path):
    from dataclasses import replace
    assert restore_problem(replace(entry(tmp_path), damaged=True), device()) == "Damaged by a later backup"


def test_newer_os_detail_explains(tmp_path):
    from ibr.core.compat import problem_detail
    text = problem_detail(entry(tmp_path), device(version="18.6"))
    assert "26.0.1" in text and "18.6" in text
    assert "same or a newer version" in text


def test_detail_none_when_ok(tmp_path):
    from ibr.core.compat import problem_detail
    assert problem_detail(entry(tmp_path), device()) is None


def battery(level, charging):
    return parse_device_info(plistlib.dumps({"UniqueDeviceID": "DEV", "DeviceName": "Phone",
                                             "ProductType": "iPhone12,1", "ProductVersion": "26.0"}),
                             plistlib.dumps({"BatteryCurrentCapacity": level, "BatteryIsCharging": charging}),
                             None, None)


def test_backup_warning_low_battery_not_charging():
    assert "15%" in backup_warning(battery(15, False))
    assert backup_warning(battery(15, True)) is None
    assert backup_warning(battery(20, False)) is None
    assert backup_warning(parse_device_info(plistlib.dumps({"ProductType": "iPhone12,1"}), None, None, None)) is None
