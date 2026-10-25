import pytest

from ibr.core.firmware import FirmwareParser, OverallPercent, StepChanged, ipsw_matches, tool_is_modern
from ibr.core.progress import Error, Finished


def test_tool_is_modern():
    modern = "  -P, --plain-progress  Print progress\n  --variant VARIANT     Use given VARIANT\n"
    assert tool_is_modern(modern)
    assert not tool_is_modern("  -l, --latest  Use latest available firmware\n")


@pytest.mark.parametrize("name, product_type, expected", [
    ("iPhone17,1_26.0.1_23A355_Restore.ipsw", "iPhone17,1", True),
    ("iPhone17,3_iPhone17,4_26.0.1_23A355_Restore.ipsw", "iPhone17,4", True),
    ("iPhone17,1_26.0.1_23A355_Restore.ipsw", "iPhone17,10", False),
    ("iPad16,3_iPad16,4_26.0_Restore.ipsw", "iPhone17,1", False),
    ("renamed-firmware.ipsw", "iPhone17,1", None),
])
def test_ipsw_matches(name, product_type, expected):
    assert ipsw_matches(name, product_type) is expected


def feed(*chunks):
    parser = FirmwareParser()
    events = []
    for chunk in chunks:
        events += parser.feed(chunk)
    return events


def test_step_progress_becomes_monotonic_overall_percent():
    events = feed("progress: 0 0.500000\n", "progress: 2 0.500000\n", "progress: 1 0.900000\n")
    percents = [e.value for e in events if isinstance(e, OverallPercent)]
    assert percents == sorted(percents)
    assert percents[0] == pytest.approx(2.5)
    assert percents[1] == pytest.approx(15 + 22.5)


def test_step_names():
    assert StepChanged(2, "Sending iOS to the device") in feed("progress: 2 0.100000\n")


def test_finished_and_errors():
    assert Finished(True, "Restore Finished") in feed("Status: Restore Finished\n")
    assert Finished(True, "DONE") in feed("DONE\n")
    assert Finished(False, "Verification Error") in feed("Status: Verification Error\n")
    assert Error("Unable to send TSS request") in feed("ERROR: Unable to send TSS request\n")


def test_target_from_recovery_device():
    from ibr.core.firmware import FirmwareTarget
    target = FirmwareTarget.from_recovery("Recovery", "iPhone17,1", "iPhone 16 Pro", "0xAA")
    assert target.ecid == "0xAA" and target.udid is None
    assert target.name == "iPhone 16 Pro"
    assert target.os_name == "iOS"
    assert target.installed == "Recovery mode"
    assert target.spec.name == "iPhone 16 Pro"


def test_target_from_unknown_recovery_device():
    from ibr.core.firmware import FirmwareTarget
    target = FirmwareTarget.from_recovery("DFU", None, None, "0xAA")
    assert target.name == "Your device"
    assert target.product_type is None


def test_target_for_ipad_uses_ipados():
    from ibr.core.firmware import FirmwareTarget
    assert FirmwareTarget.from_recovery("Recovery", "iPad16,5", None, "0x1").os_name == "iPadOS"
