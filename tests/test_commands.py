from ibr.core.commands import (
    RestoreOptions,
    backup_cmd,
    changepw_cmd,
    encryption_cmd,
    restore_cmd,
)

PREFIX = ["idevicebackup2"]


def test_backup_incremental():
    argv, env = backup_cmd("UDID1", "/b")
    assert argv == PREFIX + ["-u", "UDID1", "backup", "/b"]
    assert env == {}


def test_backup_full():
    argv, _ = backup_cmd("UDID1", "/b", full=True)
    assert argv == PREFIX + ["-u", "UDID1", "backup", "--full", "/b"]


def test_restore_defaults():
    argv, env = restore_cmd("UDID1", "/b", RestoreOptions())
    assert argv == PREFIX + ["-u", "UDID1", "restore", "--settings", "/b"]
    assert env == {}


def test_restore_all_options_and_password_in_env_only():
    options = RestoreOptions(
        source_udid="SRC",
        password="hunter2",
        system=True,
        settings=False,
        reboot=False,
        copy=True,
        remove=True,
        skip_apps=True,
    )
    argv, env = restore_cmd("UDID1", "/b", options)
    assert argv == PREFIX + [
        "-u", "UDID1", "-s", "SRC", "restore",
        "--system", "--no-reboot", "--copy", "--remove", "--skip-apps", "/b",
    ]
    assert "hunter2" not in argv
    assert env == {"BACKUP_PASSWORD": "hunter2"}


def test_restore_same_source_not_passed():
    argv, _ = restore_cmd("UDID1", "/b", RestoreOptions(source_udid="UDID1"))
    assert "-s" not in argv


def test_encryption_on():
    argv, env = encryption_cmd("UDID1", True, "pw")
    assert argv == ["idevicebackup2", "-u", "UDID1", "encryption", "on"]
    assert env == {"BACKUP_PASSWORD": "pw"}


def test_encryption_off():
    argv, env = encryption_cmd("UDID1", False, "pw")
    assert argv[-1] == "off"
    assert env == {"BACKUP_PASSWORD": "pw"}


def test_changepw():
    argv, env = changepw_cmd("UDID1", "old", "new")
    assert argv == ["idevicebackup2", "-u", "UDID1", "changepw"]
    assert env == {"BACKUP_PASSWORD": "old", "BACKUP_PASSWORD_NEW": "new"}


def test_firmware_update_local_ipsw():
    from ibr.core.commands import firmware_cmd
    argv, env = firmware_cmd("UDID1", erase=False, ipsw="/f/iPhone.ipsw", cache="/c")
    assert argv == ["idevicerestore", "-u", "UDID1", "-y", "-P", "-C", "/c", "/f/iPhone.ipsw"]
    assert env == {}


def test_firmware_restore_local_ipsw():
    from ibr.core.commands import firmware_cmd
    argv, _ = firmware_cmd("UDID1", erase=True, ipsw="/f/iPhone.ipsw", cache="/c")
    assert argv == ["idevicerestore", "-u", "UDID1", "-y", "-P", "-C", "/c", "-e", "/f/iPhone.ipsw"]


def test_firmware_by_ecid_for_recovery_mode():
    from ibr.core.commands import firmware_cmd
    argv, _ = firmware_cmd(None, erase=True, ipsw="/f/a.ipsw", cache="/c", ecid="0x1A2B")
    assert argv == ["idevicerestore", "-i", "0x1A2B", "-y", "-P", "-C", "/c", "-e", "/f/a.ipsw"]
