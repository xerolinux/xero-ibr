from dataclasses import dataclass, field
from pathlib import Path

from gi.repository import GObject, Gtk

from ..core.backups import BackupEntry
from ..core.catalog import ModelSpec
from ..core.fmt import format_date
from .device_art import DeviceArt
from .widgets import clear, hbox, label, vbox


@dataclass
class SidebarDevice:
    udid: str
    name: str
    spec: ModelSpec
    finish: str
    status: str
    status_class: str = ""
    progress: float | None = None
    backups: list[BackupEntry] = field(default_factory=list)


class Sidebar(Gtk.Box):
    __gsignals__ = {
        "device-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "backup-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    HISTORY = 3
    _browsing: Path | None = None

    def __init__(self, size_of):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("sidebar")
        self.set_size_request(270, -1)
        self._size_of = size_of
        self.append(label("DEVICES", "section-title"))
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._list = vbox(14)
        scroller.set_child(self._list)
        self.append(scroller)
        self._location = vbox(2, "location-box")
        self._location.append(label("Backups stored in", xalign=0))
        self._path = label("", "path", wrap=True)
        self._location.append(self._path)
        self.append(self._location)

    def set_location(self, path: str):
        home = str(Path.home())
        self._path.set_label("~" + path[len(home):] if path == home or path.startswith(home + "/") else path)

    def update(self, devices: list[SidebarDevice], selected: str | None, browsing: Path | None = None):
        self._browsing = browsing
        clear(self._list)
        if not devices:
            empty = label("No devices yet", "empty-box", xalign=0.5)
            self._list.append(empty)
            return
        for device in devices:
            self._list.append(self._group(device, device.udid == selected))

    def _group(self, device: SidebarDevice, active: bool) -> Gtk.Widget:
        group = vbox(4)
        header = Gtk.Button()
        header.add_css_class("flat")
        header.add_css_class("device-row")
        if active:
            header.add_css_class("active")
        content = vbox(8)
        top = hbox(10)
        art = DeviceArt(22, 34)
        art.set_device(device.spec, device.finish)
        top.append(art)
        names = vbox(2)
        names.set_valign(Gtk.Align.CENTER)
        names.append(label(device.name, "device-name", ellipsize=True))
        status = label(device.status, "device-status", ellipsize=True)
        if device.status_class:
            status.add_css_class(device.status_class)
        names.append(status)
        top.append(names)
        content.append(top)
        if device.progress is not None:
            bar = Gtk.ProgressBar(fraction=device.progress)
            bar.add_css_class("thin")
            content.append(bar)
        header.set_child(content)
        header.connect("clicked", lambda *_: self.emit("device-selected", device.udid))
        group.append(header)

        if not device.backups:
            empty = label("No backups yet", "caption", xalign=0)
            empty.set_margin_start(42)
            group.append(empty)
        for entry in device.backups[: self.HISTORY]:
            row = self._backup_row(entry)
            row.set_margin_start(24)
            group.append(row)
        return group

    def _backup_row(self, entry: BackupEntry) -> Gtk.Widget:
        row = Gtk.Button()
        row.add_css_class("flat")
        row.add_css_class("backup-row")
        row.set_tooltip_text("Browse this backup")
        if entry.path == self._browsing:
            row.add_css_class("active")
        content = hbox(8)
        when = format_date(entry.local_date) if entry.local_date else "Unknown date"
        content.append(self._expand(label(when, ellipsize=True)))
        if entry.encrypted:
            lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
            lock.add_css_class("dim")
            lock.set_tooltip_text("Encrypted")
            content.append(lock)
        size = label(self._size_of(entry) or "…", "dim")
        content.append(size)
        row.set_child(content)
        row.connect("clicked", lambda *_: self.emit("backup-activated", entry))
        return row

    @staticmethod
    def _expand(widget: Gtk.Widget) -> Gtk.Widget:
        widget.set_hexpand(True)
        return widget
