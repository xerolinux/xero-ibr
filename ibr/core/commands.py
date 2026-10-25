from dataclasses import dataclass

_TOOL = "idevicebackup2"


@dataclass(frozen=True)
class RestoreOptions:
    source_udid: str | None = None
    password: str | None = None
    system: bool = False
    settings: bool = True
    reboot: bool = True
    copy: bool = False
    remove: bool = False
    skip_apps: bool = False


def backup_cmd(udid: str, root: str, full: bool = False) -> tuple[list[str], dict]:
    return [_TOOL, "-u", udid, "backup"] + (["--full"] if full else []) + [root], {}


def restore_cmd(udid: str, root: str, options: RestoreOptions) -> tuple[list[str], dict]:
    argv = [_TOOL, "-u", udid]
    if options.source_udid and options.source_udid != udid:
        argv += ["-s", options.source_udid]
    argv.append("restore")
    flags = (
        (options.system, "--system"),
        (options.settings, "--settings"),
        (not options.reboot, "--no-reboot"),
        (options.copy, "--copy"),
        (options.remove, "--remove"),
        (options.skip_apps, "--skip-apps"),
    )
    argv += [flag for enabled, flag in flags if enabled]
    argv.append(root)
    env = {"BACKUP_PASSWORD": options.password} if options.password else {}
    return argv, env


def encryption_cmd(udid: str, enable: bool, password: str) -> tuple[list[str], dict]:
    return [_TOOL, "-u", udid, "encryption", "on" if enable else "off"], {"BACKUP_PASSWORD": password}


def changepw_cmd(udid: str, old: str, new: str) -> tuple[list[str], dict]:
    return [_TOOL, "-u", udid, "changepw"], {"BACKUP_PASSWORD": old, "BACKUP_PASSWORD_NEW": new}


def firmware_cmd(udid: str | None, erase: bool, ipsw: str, cache: str,
                 ecid: str | None = None) -> tuple[list[str], dict]:
    target = ["-i", ecid] if ecid else ["-u", udid]
    return ["idevicerestore", *target, "-y", "-P", "-C", cache] + (["-e"] if erase else []) + [ipsw], {}
