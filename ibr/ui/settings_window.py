from gi.repository import Gio, Gtk

from ..core.settings import THEMES
from ..services import keyring
from ..services.operation import log_dir
from ..services.runner import REQUIRED_TOOLS, missing_tools
from .dialog import PANEL, Dialog, confirm
from .reveal_dialog import RevealDialog
from .widgets import button, hbox, label, vbox


class SettingsWindow(Dialog):
    def __init__(self, window):
        super().__init__(window, "Settings", *PANEL)
        self._window = window
        self._settings = window.settings
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        body = vbox(22)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(22)
        scroller.set_child(body)
        self.set_child(scroller)

        device = window.current_device_info()

        self._folder_label = label(self._settings.backup_dir, "row-sub", wrap=True)
        folder = button("Change…", None, "outline")
        folder.connect("clicked", self._pick_folder)
        keep = Gtk.SpinButton.new_with_range(1, 10, 1)
        keep.set_value(self._settings.keep_history)
        keep.set_valign(Gtk.Align.CENTER)
        keep.update_property([Gtk.AccessibleProperty.LABEL], ["Backups to keep per device"])
        keep.connect("value-changed", lambda spin: self._set("keep_history", int(spin.get_value())))
        body.append(self._section("Backups", [
            self._row("Backup folder", None, folder, sub_widget=self._folder_label),
            self._row("Backups to keep per device", "Older backups are deleted after a new one finishes. "
                      "Unchanged files are shared between backups, so extra copies use little space.", keep),
            self._switch("Always make a full backup", "Ignore the previous backup and copy everything again.",
                         "always_full"),
            self._switch("Warn when disk space is low", "Checks free space before each backup.", "warn_low_space"),
        ]))

        change = button("Change…", None, "outline")
        change.set_sensitive(bool(device and device.will_encrypt))
        change.connect("clicked", lambda *_: window.change_password())
        forget = button("Forget", None, "outline")
        forget.connect("clicked", lambda *_: keyring.clear())
        saved_rows = []
        for udid, name in window.known_devices().items():
            secret = keyring.lookup(udid)
            if secret:
                show = button("Show…", None, "outline")
                show.connect("clicked", lambda _b, n=name, s=secret: self._reveal(n, s))
                saved_rows.append(self._row(f"Saved password: {name}", "Shown only after you confirm.", show))
        body.append(self._section("Encryption", [
            self._switch("Remember passwords in the keyring", "Stored with your desktop's Secret Service "
                         "(GNOME Keyring or KWallet).", "remember_password"),
            self._row("Change backup password", "Needs a connected device with encryption on.", change),
            *saved_rows,
            self._row("Forget saved passwords", "Removes every iBR password from the keyring.", forget),
        ]))

        body.append(self._section("Restore", [
            self._switch("Include system files (advanced)", "Also restores data from the backup's system areas, "
                         "beyond your apps and settings. Rarely needed, and best left off when restoring to a "
                         "different device.", "restore_system"),
            self._switch("Restore device settings", None, "restore_settings"),
            self._switch("Restart the device when finished", None, "restore_reboot"),
            self._switch("Copy the backup before restoring", "Keeps the original untouched. Needs extra space.",
                         "restore_copy"),
            self._switch("Remove items not in the backup", None, "restore_remove"),
            self._switch("Skip reinstalling apps", None, "restore_skip_apps"),
        ]))

        unpair = button("Forget", None, "outline")
        unpair.set_sensitive(device is not None)
        unpair.connect("clicked", lambda *_: window.unpair_current())
        body.append(self._section("Devices", [
            self._switch("Detect devices automatically", "Watches for devices instead of waiting for Scan.",
                         "auto_detect"),
            self._switch("Back up automatically when connected", None, "auto_backup"),
            self._row("Forget this computer on the device", "The device asks to Trust again next time.", unpair),
        ]))

        theme = Gtk.DropDown.new_from_strings([name.title() for name in THEMES])
        theme.set_selected(THEMES.index(self._settings.theme))
        theme.set_valign(Gtk.Align.CENTER)
        theme.update_property([Gtk.AccessibleProperty.LABEL], ["Theme"])
        theme.connect("notify::selected", lambda drop, _p: self._set("theme", THEMES[drop.get_selected()]))
        body.append(self._section("Behaviour", [
            self._switch("Notify when finished", None, "notify"),
            self._switch("Keep the computer awake during backups", None, "keep_awake"),
            self._row("Theme", None, theme),
            self._switch("Show serial number and UDID", None, "show_identifiers"),
        ]))

        logs = button("Open", None, "outline")
        logs.connect("clicked", self._open_logs)
        missing = set(missing_tools())
        tools = vbox(4)
        for tool in REQUIRED_TOOLS:
            tools.append(label(f"{'✗' if tool in missing else '✓'}  {tool}", "mono"))
        body.append(self._section("Advanced", [
            self._row("Log folder", str(log_dir()), logs),
            self._row("Required tools", "From libimobiledevice.", tools),
            self._row("Supported devices", "iPhone and iPad with iOS/iPadOS 15 and newer.", None),
        ]))

    def _reveal(self, name: str, secret: str):
        confirm(self, "Show the saved password?", f"The backup password for {name} will be shown on screen.",
                "Show", lambda ok: ok and RevealDialog(self, name, secret).present())

    def _section(self, title: str, rows: list[Gtk.Widget]) -> Gtk.Widget:
        section = vbox(8)
        section.append(label(title.upper(), "section-title"))
        group = vbox(0, "settings-group")
        for row in rows:
            group.append(row)
        section.append(group)
        return section

    def _row(self, title: str, sub: str | None, control: Gtk.Widget | None, sub_widget=None) -> Gtk.Widget:
        row = hbox(16, "settings-row")
        text = vbox(2)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        text.append(label(title, "row-title", wrap=True))
        if sub:
            text.append(label(sub, "row-sub", wrap=True))
        if sub_widget:
            text.append(sub_widget)
        row.append(text)
        if control:
            control.set_valign(Gtk.Align.CENTER)
            row.append(control)
        return row

    def _switch(self, title: str, sub: str | None, attr: str) -> Gtk.Widget:
        switch = Gtk.Switch(active=getattr(self._settings, attr))
        switch.update_property([Gtk.AccessibleProperty.LABEL], [title])
        switch.connect("notify::active", lambda sw, _p: self._set(attr, sw.get_active()))
        return self._row(title, sub, switch)

    def _set(self, attr: str, value):
        setattr(self._settings, attr, value)
        self._settings.save()
        self._window.on_setting_changed(attr)

    def _pick_folder(self, *_):
        dialog = Gtk.FileDialog(title="Choose backup folder", modal=True)
        dialog.set_initial_folder(Gio.File.new_for_path(self._settings.backup_dir))

        def chosen(source, result):
            try:
                folder = source.select_folder_finish(result)
            except Exception:
                return
            if folder and folder.get_path():
                self._folder_label.set_label(folder.get_path())
                self._set("backup_dir", folder.get_path())

        dialog.select_folder(self, None, chosen)

    def _open_logs(self, *_):
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(folder))).launch(self, None, None)
