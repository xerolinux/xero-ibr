import json

from ibr.core.settings import Settings, default_backup_dir


def test_missing_file_gives_defaults(tmp_path):
    settings = Settings.load(tmp_path / "settings.json")
    assert settings.backup_dir == str(default_backup_dir())
    assert settings.theme == "dark"
    assert settings.auto_detect is True
    assert settings.always_full is False


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    settings = Settings.load(path)
    settings.theme = "dark"
    settings.always_full = True
    settings.save()
    loaded = Settings.load(path)
    assert loaded.theme == "dark"
    assert loaded.always_full is True


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert Settings.load(path).theme == "dark"


def test_unknown_keys_and_wrong_types_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": 5, "always_full": True, "bogus": 1}))
    settings = Settings.load(path)
    assert settings.theme == "dark"
    assert settings.always_full is True
    assert not hasattr(settings, "bogus")


def test_invalid_theme_value_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "neon"}))
    assert Settings.load(path).theme == "dark"


def test_default_backup_dir_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_backup_dir() == tmp_path / "ibr" / "backups"


def test_keep_history_default_and_bounds(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings.load(path).keep_history == 3
    path.write_text(json.dumps({"keep_history": 0}))
    assert Settings.load(path).keep_history == 3
    path.write_text(json.dumps({"keep_history": 5}))
    assert Settings.load(path).keep_history == 5


def test_firmware_folder_follows_the_xdg_download_folder(tmp_path, monkeypatch):
    from ibr.core.settings import default_firmware_dir
    config = tmp_path / "config"
    config.mkdir()
    (config / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Transfers"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_firmware_dir() == tmp_path / "Transfers" / "iPSW"
    (config / "user-dirs.dirs").unlink()
    assert default_firmware_dir() == tmp_path / "Downloads" / "iPSW"
    assert Settings.load(tmp_path / "s.json").firmware_dir == str(tmp_path / "Downloads" / "iPSW")


def test_grid_view_is_the_default_even_for_old_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"files_view_mode": "list", "backup_view_mode": "list"}))
    settings = Settings.load(path)
    assert (settings.files_layout, settings.backup_layout) == ("grid", "grid")
