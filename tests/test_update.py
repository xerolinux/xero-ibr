from ibr.core.update import asset_url, clean_env, latest_version, newer, parse_checksum


def test_newer():
    assert newer("0.1.42", "0.1.9")
    assert not newer("0.1.9", "0.1.42")
    assert not newer("0.1.42", "0.1.42")


def test_latest_version_from_release_redirect():
    assert latest_version("https://github.com/o/r/releases/tag/v0.1.42") == "0.1.42"
    assert latest_version("https://github.com/o/r/releases") is None
    assert latest_version("https://github.com/login?return_to=x") is None


def test_asset_url():
    assert asset_url("o/r", "0.1.42", "x86_64") == \
        "https://github.com/o/r/releases/download/v0.1.42/iBR-0.1.42-x86_64.AppImage"


def test_parse_checksum_matches_file_name():
    digest = "ab" * 32
    assert parse_checksum(f"{digest}  iBR-0.1.42-x86_64.AppImage\n", "iBR-0.1.42-x86_64.AppImage") == digest
    assert parse_checksum(f"{digest}  other.AppImage\n", "iBR-0.1.42-x86_64.AppImage") is None
    assert parse_checksum("Not Found", "iBR-0.1.42-x86_64.AppImage") is None


def test_clean_env_drops_appimage_runtime_variables():
    env = {"HOME": "/home/u", "APPIMAGE": "/a", "APPDIR": "/tmp/.mount", "LD_PRELOAD": "x.so",
           "PYTHONHOME": "/tmp/.mount/usr", "SHARUN_DIR": "/tmp/.mount", "PATH": "/tmp/.mount/bin:/usr/bin"}
    cleaned = clean_env(env, "/tmp/.mount")
    assert cleaned == {"HOME": "/home/u", "PATH": "/usr/bin"}
