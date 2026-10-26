import pytest

from ibr.core.recovery import (
    UDEV_RULE,
    UDEV_RULE_PATH,
    install_script,
    rule_installed,
    UsbRecovery,
    clean_transfers,
    parse_irecovery,
    scan_usb,
    usbmuxd_install_hint,
)


def usb_device(root, name, vendor, product, serial=None):
    folder = root / name
    folder.mkdir()
    (folder / "idVendor").write_text(vendor + "\n")
    (folder / "idProduct").write_text(product + "\n")
    if serial is not None:
        (folder / "serial").write_text(serial + "\n")


SERIAL = "SDOM:01 CPID:8140 CPRV:11 CPFM:03 SCEP:01 BDID:0C ECID:001A2B3C4D5E6F70 IBFL:3C SRTG:[iBoot-11881.1]"


def test_scan_usb_finds_recovery_and_dfu(tmp_path):
    usb_device(tmp_path, "1-1", "05ac", "1281", SERIAL)
    usb_device(tmp_path, "1-2", "05ac", "1227", "CPID:8140 ECID:00000000000000AA")
    usb_device(tmp_path, "1-3", "05ac", "12a8", "a1b2c3")
    usb_device(tmp_path, "1-4", "046d", "c52b", "logitech")
    found = scan_usb(tmp_path)
    assert found == [
        UsbRecovery("Recovery", "0x1A2B3C4D5E6F70", "1-1"),
        UsbRecovery("DFU", "0xAA", "1-2"),
    ]


def test_scan_usb_without_serial(tmp_path):
    usb_device(tmp_path, "2-1", "05ac", "1281")
    assert scan_usb(tmp_path) == [UsbRecovery("Recovery", None, "2-1")]


def test_scan_usb_missing_root(tmp_path):
    assert scan_usb(tmp_path / "nope") == []


def test_parse_irecovery():
    text = ("CPID: 0x8140\nECID: 0x001a2b3c4d5e6f70\nMODE: Recovery\nPRODUCT: iPhone17,1\n"
            "MODEL: d93ap\nNAME: iPhone 16 Pro\n")
    assert parse_irecovery(text) == {"mode": "Recovery", "product_type": "iPhone17,1", "name": "iPhone 16 Pro",
                                     "ecid": "0x001a2b3c4d5e6f70"}


def test_parse_irecovery_empty():
    assert parse_irecovery("ERROR: Unable to connect to device\n") == {}


@pytest.mark.parametrize("os_release, expected", [
    ('ID=arch\n', "sudo pacman -S usbmuxd"),
    ('ID=cachyos\nID_LIKE=arch\n', "sudo pacman -S usbmuxd"),
    ('ID=ubuntu\nID_LIKE=debian\n', "sudo apt install usbmuxd"),
    ('ID="fedora"\n', "sudo dnf install usbmuxd"),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "sudo zypper install usbmuxd"),
    ('ID=void\n', "sudo xbps-install usbmuxd"),
    ('ID=artix\n', "sudo pacman -S usbmuxd"),
    ('ID=gentoo\n', "sudo emerge app-pda/usbmuxd"),
    ('ID=devuan\nID_LIKE=debian\n', "sudo apt install usbmuxd"),
    ('ID=alpine\n', "sudo apk add usbmuxd"),
    ('ID=nixos\n', "services.usbmuxd.enable = true;"),
    ('ID=something\n', "Install the usbmuxd package from your distribution."),
])
def test_usbmuxd_install_hint(os_release, expected):
    assert usbmuxd_install_hint(os_release) == expected


def test_udev_rule_only_matches_recovery_ids():
    assert 'ATTR{idVendor}=="05ac"' in UDEV_RULE
    for pid in ("1227", "1281", "1881"):
        assert pid in UDEV_RULE
    assert "12a8" not in UDEV_RULE
    assert 'TAG+="uaccess"' in UDEV_RULE


def test_clean_transfers(tmp_path):
    (tmp_path / "drag-abc").mkdir()
    (tmp_path / "drag-abc" / "IMG.HEIC").write_bytes(b"x")
    (tmp_path / "preview").mkdir()
    (tmp_path / "loose.tmp").write_bytes(b"y")
    clean_transfers(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_clean_transfers_missing_folder(tmp_path):
    clean_transfers(tmp_path / "nope")


def test_udev_rule_keeps_apple_devices_out_of_usb_autosuspend():
    power = [line for line in UDEV_RULE.splitlines() if "power/control" in line]
    assert len(power) == 1
    assert 'ATTR{idVendor}=="05ac"' in power[0] and 'ACTION=="add"' in power[0]
    assert "echo on > /sys%p/power/control" in power[0]


def test_udev_rule_runs_after_power_tools():
    assert UDEV_RULE_PATH == "/etc/udev/rules.d/99-ibr.rules"


def test_packaged_rule_matches():
    from pathlib import Path
    assert (Path(__file__).parent.parent / "data" / "99-ibr.rules").read_text() == UDEV_RULE


def test_rule_installed(tmp_path):
    etc, lib = tmp_path / "etc.rules", tmp_path / "lib.rules"
    assert not rule_installed([etc, lib])
    lib.write_text("old rule\n")
    assert not rule_installed([etc, lib])
    etc.write_text(UDEV_RULE)
    assert rule_installed([etc, lib])


def test_install_script_writes_rule_and_drops_old_file(tmp_path):
    import subprocess
    etc = tmp_path / "rules.d"
    etc.mkdir()
    (etc / "70-ibr-recovery.rules").write_text("old\n")
    script = install_script().replace("/etc/udev/rules.d", str(etc))
    script = script.split(" && udevadm")[0]
    subprocess.run(["sh", "-c", script], check=True)
    assert (etc / "99-ibr.rules").read_text() == UDEV_RULE
    assert not (etc / "70-ibr-recovery.rules").exists()
    assert install_script().endswith("udevadm control --reload-rules && udevadm trigger --subsystem-match=usb "
                                     "--attr-match=idVendor=05ac")
