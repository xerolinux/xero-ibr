from ibr.core.usbmux import (
    find_usbmuxd,
    has_systemd,
    muxable_device_present,
    start_command,
    status_tip,
)
from test_recovery import usb_device


def test_find_usbmuxd_outside_user_path():
    assert find_usbmuxd(lambda name: None, lambda path: path == "/usr/sbin/usbmuxd") == "/usr/sbin/usbmuxd"
    assert find_usbmuxd(lambda name: "/usr/bin/usbmuxd", lambda path: False) == "/usr/bin/usbmuxd"
    assert find_usbmuxd(lambda name: None, lambda path: False) is None


def test_has_systemd(tmp_path):
    assert not has_systemd(tmp_path)
    (tmp_path / "run" / "systemd" / "system").mkdir(parents=True)
    assert has_systemd(tmp_path)


def test_start_command_per_init():
    assert start_command(True, "/usr/bin/usbmuxd") == ["systemctl", "start", "usbmuxd.service"]
    assert start_command(False, "/usr/sbin/usbmuxd") == ["/usr/sbin/usbmuxd", "--user", "usbmux", "--enable-exit"]


def test_status_tip_never_mentions_systemctl_without_systemd():
    assert "systemctl status usbmuxd" in status_tip(True)
    assert "systemctl" not in status_tip(False)


def test_muxable_device_present(tmp_path):
    usb_device(tmp_path, "1-1", "05ac", "1281")
    usb_device(tmp_path, "1-2", "046d", "12a8")
    assert not muxable_device_present(tmp_path)
    usb_device(tmp_path, "1-3", "05ac", "12a8")
    assert muxable_device_present(tmp_path)
    assert not muxable_device_present(tmp_path / "missing")
