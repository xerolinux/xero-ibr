import gi

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret  # noqa: E402

_SCHEMA = Secret.Schema.new(
    "com.techxero.ibr.BackupPassword",
    Secret.SchemaFlags.NONE,
    {"udid": Secret.SchemaAttributeType.STRING},
)


def lookup(udid: str) -> str | None:
    try:
        return Secret.password_lookup_sync(_SCHEMA, {"udid": udid}, None)
    except GLib.Error:
        return None


def store(udid: str, name: str, password: str) -> bool:
    try:
        return Secret.password_store_sync(
            _SCHEMA, {"udid": udid}, Secret.COLLECTION_DEFAULT,
            f"iBackup/Restore backup password for {name}", password, None)
    except GLib.Error:
        return False


def clear(udid: str | None = None) -> bool:
    try:
        return Secret.password_clear_sync(_SCHEMA, {"udid": udid} if udid else {}, None)
    except GLib.Error:
        return False
