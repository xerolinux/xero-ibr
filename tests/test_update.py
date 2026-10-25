import json

from ibr.core.update import clean_env, newer, pick_update

RELEASE = {
    "tag_name": "v0.1.42",
    "assets": [
        {"name": "iBR-0.1.42-x86_64.AppImage", "browser_download_url": "https://github.com/o/r/a.AppImage",
         "size": 98_000_000, "digest": "sha256:" + "ab" * 32},
        {"name": "iBR-0.1.42-x86_64.AppImage.zsync", "browser_download_url": "https://github.com/o/r/a.zsync",
         "size": 300_000},
        {"name": "iBR-0.1.42-aarch64.AppImage", "browser_download_url": "https://github.com/o/r/b.AppImage",
         "size": 97_000_000},
    ],
}


def test_newer():
    assert newer("0.1.42", "0.1.9")
    assert not newer("0.1.9", "0.1.42")
    assert not newer("0.1.42", "0.1.42")


def test_pick_update_for_arch():
    info = pick_update(json.dumps(RELEASE).encode(), "x86_64", "0.1.41")
    assert info.version == "0.1.42"
    assert info.url == "https://github.com/o/r/a.AppImage"
    assert info.size == 98_000_000
    assert info.sha256 == "ab" * 32


def test_pick_update_without_digest():
    info = pick_update(json.dumps(RELEASE).encode(), "aarch64", "0.1.41")
    assert info.url == "https://github.com/o/r/b.AppImage"
    assert info.sha256 is None


def test_no_update_when_current():
    assert pick_update(json.dumps(RELEASE).encode(), "x86_64", "0.1.42") is None


def test_no_update_without_matching_asset():
    assert pick_update(json.dumps(RELEASE).encode(), "riscv64", "0.1.1") is None


def test_bad_payload():
    assert pick_update(b"rate limited", "x86_64", "0.1.1") is None


def test_clean_env_drops_appimage_runtime_variables():
    env = {"HOME": "/home/u", "APPIMAGE": "/a", "APPDIR": "/tmp/.mount", "LD_PRELOAD": "x.so",
           "PYTHONHOME": "/tmp/.mount/usr", "SHARUN_DIR": "/tmp/.mount", "PATH": "/tmp/.mount/bin:/usr/bin"}
    cleaned = clean_env(env, "/tmp/.mount")
    assert cleaned == {"HOME": "/home/u", "PATH": "/usr/bin"}
