import os
import plistlib
import zipfile

from ibr.core.ipsw_library import IpswInfo, best_for, ipsw_state, read_ipsw, scan_folder


def make_ipsw(path, version, build, models, mtime=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BuildManifest.plist", plistlib.dumps(
            {"ProductVersion": version, "ProductBuildVersion": build, "SupportedProductTypes": models}))
        archive.writestr("kernelcache.release.x", b"k" * 100)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def test_reads_version_and_devices_from_inside_the_file(tmp_path):
    path = make_ipsw(tmp_path / "renamed.ipsw", "27.2", "24B119", ["iPhone17,1", "iPhone17,2"])
    info = read_ipsw(path)
    assert (info.version, info.build, info.models) == ("27.2", "24B119", ("iPhone17,1", "iPhone17,2"))
    assert info.size == path.stat().st_size


def test_falls_back_to_the_file_name(tmp_path):
    path = tmp_path / "iPhone17,1_26.1_23B85_Restore.ipsw"
    path.write_bytes(b"not a zip")
    info = read_ipsw(path)
    assert (info.version, info.build, info.models) == ("26.1", "23B85", ("iPhone17,1",))
    junk = tmp_path / "mystery.ipsw"
    junk.write_bytes(b"x")
    assert read_ipsw(junk).models == ()


def test_scan_lists_newest_first_and_skips_other_files(tmp_path):
    make_ipsw(tmp_path / "a.ipsw", "26.1", "23B85", ["iPhone17,1"])
    make_ipsw(tmp_path / "b.ipsw", "27.2", "24B119", ["iPhone17,1"])
    make_ipsw(tmp_path / "c.ipsw", "26.10", "23H30", ["iPad16,3"])
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "d.ipsw.part").write_bytes(b"x")
    assert [i.build for i in scan_folder(tmp_path)] == ["24B119", "23H30", "23B85"]
    assert scan_folder(tmp_path / "missing") == []


def info(build, models, version="27.2"):
    return IpswInfo(f"/x/{build}.ipsw", version, build, tuple(models), 1)


def test_states():
    signed = {"24B119"}
    assert ipsw_state(info("24B119", ["iPhone17,1"]), "iPhone17,1", signed) == "fits"
    assert ipsw_state(info("23B85", ["iPhone17,1"]), "iPhone17,1", signed) == "unsigned"
    assert ipsw_state(info("24B119", ["iPad16,3"]), "iPhone17,1", signed) == "other"
    assert ipsw_state(info("24B119", []), "iPhone17,1", signed) == "unknown"
    assert ipsw_state(info("23B85", ["iPhone17,1"]), "iPhone17,1", None) == "fits"


def test_best_for_prefers_signed_then_newest():
    files = [info("24B119", ["iPhone17,1"]), info("23B85", ["iPhone17,1"], "26.1"), info("x", ["iPad16,3"])]
    assert best_for(files, "iPhone17,1", {"23B85"}).build == "23B85"
    assert best_for(files, "iPhone17,1", {"none"}).build == "24B119"
    assert best_for(files, "iPhone99,9", None) is None
