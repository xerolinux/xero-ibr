import json

import pytest

from ibr.core.firmware import (FirmwareParser, OverallPercent, SignedIpsw, StepChanged, appledb_candidates, default_choice,
                                ipsw_choices,
                                appledb_signed_ipsw, ipsw_matches, merge_signed, signed_ipsws,
                                tool_is_modern)
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


def _catalog(*firmwares):
    return json.dumps({"identifier": "iPhone12,1", "firmwares": list(firmwares)}).encode()


def _fw(version, build, signed, url=None):
    return {"identifier": "iPhone12,1", "version": version, "buildid": build, "signed": signed,
            "filesize": 10706900826, "sha256sum": "7db7", "releasedate": "2026-09-28T18:54:11Z",
            "url": url or f"https://updates.cdn-apple.com/x/iPhone12,1_{version}_{build}_Restore.ipsw"}


def test_signed_ipsws_keeps_only_signed_with_exact_apple_file_names():
    data = _catalog(_fw("27.0.1", "24A446", True), _fw("27.0", "24A437", False),
                    _fw("26.6.2", "23G90", True,
                        "https://updates.cdn-apple.com/y/iPhone11,8,iPhone12,1_26.6.2_23G90_Restore.ipsw"))
    found = signed_ipsws(data)
    assert [(f.version, f.build, f.filename) for f in found] == [
        ("27.0.1", "24A446", "iPhone12,1_27.0.1_24A446_Restore.ipsw"),
        ("26.6.2", "23G90", "iPhone11,8,iPhone12,1_26.6.2_23G90_Restore.ipsw"),
    ]
    assert found[0].size == 10706900826 and found[0].sha256 == "7db7"
    assert found[0].url.endswith("/iPhone12,1_27.0.1_24A446_Restore.ipsw")


def test_signed_ipsws_bad_data():
    assert signed_ipsws(b"<html>") == []
    assert signed_ipsws(_catalog({"signed": True})) == []


def test_appledb_candidates_latest_major_device_builds_only():
    index = json.dumps(["iOS;23G90", "iOS;24A446", "iOS;24B115", "iOS;24B5110a", "iOS;24B114-sim",
                        "iOS;24B113-27B48-SDK", "iPadOS;24B115", "Accessory Firmware;1.0"]).encode()
    assert appledb_candidates(index, "iOS") == ["iOS;24A446", "iOS;24B115", "iOS;24B5110a"]
    assert appledb_candidates(index, "iPadOS") == ["iPadOS;24B115"]
    assert appledb_candidates(b"nope", "iOS") == []


def _appledb(signed, device="iPhone12,1"):
    return json.dumps({"version": "27.2 RC", "build": "24B115", "signed": signed, "sources": [
        {"type": "ota", "deviceMap": [device], "links": [{"url": "https://x/ota.zip"}]},
        {"type": "ipsw", "deviceMap": [device], "size": 10977004142, "hashes": {"sha2-256": "b558"},
         "links": [{"url": "https://updates.cdn-apple.com/z/iPhone12,1_27.2_24B115_Restore.ipsw"}]},
    ]}).encode()


def test_appledb_signed_ipsw_for_device():
    found = appledb_signed_ipsw(_appledb(["iPhone12,1", "iPhone13,1"]), "iPhone12,1")
    assert found == SignedIpsw("27.2 RC", "24B115", "iPhone12,1_27.2_24B115_Restore.ipsw",
                               "https://updates.cdn-apple.com/z/iPhone12,1_27.2_24B115_Restore.ipsw",
                               10977004142, "b558")
    assert appledb_signed_ipsw(_appledb(["iPhone13,1"]), "iPhone12,1") is None
    assert appledb_signed_ipsw(_appledb(["iPhone12,1"], device="iPhone13,1"), "iPhone12,1") is None
    assert appledb_signed_ipsw(b"<html>", "iPhone12,1") is None


def test_merge_signed_newest_build_first_without_duplicates():
    release = SignedIpsw("27.0.1", "24A446", "a.ipsw", "u", None, None)
    rc = SignedIpsw("27.2 RC", "24B115", "b.ipsw", "u", None, None)
    assert merge_signed([release], [rc, release]) == [rc, release]


RC = SignedIpsw("27.2 RC", "24B115", "rc.ipsw", "u", None, None)
BETA = SignedIpsw("27.2 beta 4", "24B5110a", "b4.ipsw", "u", None, None)
RELEASE = SignedIpsw("27.0.1", "24A446", "r.ipsw", "u", None, None)


def test_choices_tag_installed_and_latest_release():
    assert ipsw_choices([RC, BETA, RELEASE], "24B115") == [
        "27.2 RC (24B115) · installed", "27.2 beta 4 (24B5110a)", "27.0.1 (24A446) · latest release"]


def test_default_choice_prefers_installed_then_latest_release():
    assert default_choice([RC, BETA, RELEASE], "24B115") == 0
    assert default_choice([RC, BETA, RELEASE], "24B9999") == 2
    assert default_choice([RC, BETA, RELEASE], None) == 2
    assert default_choice([RC, BETA], None) == 0
