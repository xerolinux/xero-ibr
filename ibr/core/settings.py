import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

THEMES = ("system", "light", "dark")


def xdg_dir(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def default_backup_dir() -> Path:
    return xdg_dir("XDG_DATA_HOME", ".local/share") / "ibr" / "backups"


def default_settings_path() -> Path:
    return xdg_dir("XDG_CONFIG_HOME", ".config") / "ibr" / "settings.json"


@dataclass
class Settings:
    backup_dir: str = field(default_factory=lambda: str(default_backup_dir()))
    keep_history: int = 3
    always_full: bool = False
    warn_low_space: bool = True
    remember_password: bool = True
    restore_system: bool = False
    restore_settings: bool = True
    restore_reboot: bool = True
    restore_copy: bool = False
    restore_remove: bool = False
    restore_skip_apps: bool = False
    auto_detect: bool = True
    auto_backup: bool = False
    notify: bool = True
    keep_awake: bool = True
    theme: str = "dark"
    show_identifiers: bool = False

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = Path(path or default_settings_path())
        settings = cls()
        settings._path = path
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings
        for f in fields(cls):
            value = data.get(f.name)
            if type(value) is type(getattr(settings, f.name)):
                setattr(settings, f.name, value)
        if settings.theme not in THEMES:
            settings.theme = "dark"
        if not 1 <= settings.keep_history <= 10:
            settings.keep_history = 3
        return settings

    def save(self):
        path = getattr(self, "_path", None) or default_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, path)
