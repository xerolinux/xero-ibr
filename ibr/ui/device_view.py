from gi.repository import GObject, Gtk

from ..core.backups import BackupEntry
from ..core.deviceinfo import DeviceInfo
from ..core.fmt import format_ago, format_size
from ..core.support import MIN_OS_LABEL, is_supported
from .device_art import DeviceArt
from .progress_card import ProgressCard
from .widgets import InfoCard, button, hbox, label, set_button_text, set_classes, vbox


class DeviceView(Gtk.Box):
    __gsignals__ = {
        "backup": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "restore": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "manage": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "files": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "software": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "cancel": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(spacing=48)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(44)
        self.set_margin_end(44)
        self.set_valign(Gtk.Align.CENTER)

        self.art = DeviceArt(330, 450)
        self.art.set_valign(Gtk.Align.CENTER)
        self.append(self.art)

        column = vbox(14)
        column.set_hexpand(True)
        column.set_valign(Gtk.Align.CENTER)
        self.append(column)

        heading = vbox(6)
        self._pill = label("", "pill", xalign=0.5)
        self._pill.set_halign(Gtk.Align.START)
        self._name = label("", "h1", ellipsize=True)
        self._subtitle = label("", "subtitle", wrap=True)
        for widget in (self._pill, self._name, self._subtitle):
            heading.append(widget)
        column.append(heading)
        self._banner = label("", "banner", wrap=True)
        self._banner.set_visible(False)
        column.append(self._banner)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        column.append(self._stack)

        idle = vbox(14)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        self.storage = InfoCard("Storage")
        self.last_backup = InfoCard("Last backup")
        self.last_backup.set_tooltip_text(
            "Backups hold your data and settings. Apps are downloaded again from the App Store, iOS itself is "
            "not included, and photos kept in iCloud stay in iCloud, so a backup is smaller than the storage "
            "used on the device.")
        self.battery = InfoCard("Battery")
        self.model = InfoCard("Model")
        for index, card in enumerate((self.storage, self.last_backup, self.battery, self.model)):
            grid.attach(card, index % 2, index // 2, 1, 1)
        idle.append(grid)
        self._identifiers = label("", "caption", wrap=True)
        idle.append(self._identifiers)

        actions = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self._backup = button("Back Up Now", "document-save-symbolic", "primary", "big")
        self._restore = button("Restore Backup", "document-revert-symbolic", "outline", "big")
        self._manage = button("Manage Backups", "folder-open-symbolic", "outline", "big")
        self._backup.connect("clicked", lambda *_: self.emit("backup"))
        self._restore.connect("clicked", lambda *_: self.emit("restore"))
        self._manage.connect("clicked", lambda *_: self.emit("manage"))
        self._files = button("Browse Files", "folder-symbolic", "outline", "big")
        self._files.connect("clicked", lambda *_: self.emit("files"))
        self._software = button("Update or Restore iOS", "software-update-available-symbolic", "outline", "big")
        self._software.connect("clicked", lambda *_: self.emit("software"))
        self._software.set_halign(Gtk.Align.CENTER)
        for index, widget in enumerate((self._backup, self._restore, self._manage, self._files)):
            actions.attach(widget, index % 2, index // 2, 1, 1)
        actions.attach(self._software, 0, 2, 2, 1)
        idle.append(actions)

        self._stack.add_named(idle, "idle")

        busy = vbox(18)
        self.progress = ProgressCard()
        busy.append(self.progress)
        cancel_row = hbox(12)
        self._cancel = button("Cancel Backup", None, "danger", "big")
        self._cancel.connect("clicked", lambda *_: self.emit("cancel"))
        cancel_row.append(self._cancel)
        self._busy_note = label("Restore and Manage Backups are available when this finishes.", "caption", wrap=True)
        self._busy_note.set_valign(Gtk.Align.CENTER)
        self._busy_note.set_hexpand(True)
        cancel_row.append(self._busy_note)
        busy.append(cancel_row)
        self._stack.add_named(busy, "busy")

    _busy = False
    _udid = None
    _home = None

    def update(self, info: DeviceInfo, latest: BackupEntry | None, latest_size: str | None,
               show_identifiers: bool, has_backups: bool, home=None):
        spec = info.spec
        if info.udid != self._udid:
            self._udid = info.udid
            self._banner.set_visible(False)
        self.art.set_device(spec, info.finish, info.product_type)
        if home is not self._home:
            self._home = home
            self.art.set_home(home)
        supported = is_supported(info.os_version)
        self._name.set_label(info.name or spec.name)
        self._subtitle.set_label(f"{spec.name} · {info.os_label}")
        if not self._busy:
            if supported:
                self._set_pill("Paired and trusted", "success")
            else:
                self._set_pill(f"Needs {MIN_OS_LABEL} or later", "warn")
            self._pill.set_tooltip_text("Update the device in Settings > General > Software Update.")

        if info.total_bytes and info.used_bytes is not None:
            system = f"Includes {format_size(info.system_bytes)} for {info.os_label.split(' ')[0]}" \
                if info.system_bytes else ""
            self.storage.update(f"{format_size(info.used_bytes)} of {format_size(info.total_bytes)}", system,
                                fraction=info.used_bytes / info.total_bytes)
        else:
            self.storage.update("Unknown")
        if latest and latest.local_date:
            details = ["Encrypted" if latest.encrypted else "Not encrypted"]
            if latest_size:
                details.append(latest_size)
            self.last_backup.update(format_ago(latest.local_date), " · ".join(details))
        else:
            self.last_backup.update("Never", "Back up to keep a copy on this computer")
        if info.battery_level is not None:
            self.battery.update(f"{info.battery_level}%" + (" · Charging" if info.charging else ""))
        else:
            self.battery.update("Unknown")
        self.model.update(info.model_number or spec.name, info.product_type)

        self._identifiers.set_visible(show_identifiers)
        self._identifiers.set_label(f"Serial {info.serial} · UDID {info.udid}")
        self._backup.set_sensitive(supported)
        self._restore.set_sensitive(supported and has_backups)
        self._manage.set_sensitive(has_backups)
        self._files.set_sensitive(supported)
        set_button_text(self._software, f"Update or Restore {info.os_label.split(' ')[0]}")
        self._software.set_sensitive(True)

    def _set_pill(self, text: str, kind: str):
        self._pill.set_label(text)
        set_classes(self._pill, kind, keep=("pill",))

    def set_busy(self, kind: str):
        self._busy = True
        self.progress.reset(kind)
        self._cancel.set_label("Cancel Backup" if kind == "backup" else "Cancel")
        self._set_pill("Backup in progress · keep the device connected", "info")
        self._banner.set_visible(False)
        self._stack.set_visible_child_name("busy")

    def set_idle(self):
        self._busy = False
        self.progress.finish(False)
        self._stack.set_visible_child_name("idle")

    def show_banner(self, kind: str, text: str):
        self._banner.set_label(text)
        set_classes(self._banner, kind, keep=("banner",))
        self._banner.set_visible(bool(text))
