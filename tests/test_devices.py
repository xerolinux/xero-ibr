import os

from gi.repository import GLib

from ibr.services import devices


def test_monitor_recovers_from_a_hung_device_command(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"idevice_id": "echo UDID", "idevicepair": "exec sleep 30", "irecovery": "exit 0"}.items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(devices, "scan_usb", lambda: [])
    monkeypatch.setattr(devices.DeviceMonitor, "COMMAND_SECONDS", 1)

    monitor = devices.DeviceMonitor()
    loop = GLib.MainLoop()
    monitor.connect("scanning", lambda _, active: active or loop.quit())
    GLib.timeout_add_seconds(5, loop.quit)
    monitor.scan()
    loop.run()

    assert not monitor._busy
    assert monitor.devices["UDID"].state == "trust"
