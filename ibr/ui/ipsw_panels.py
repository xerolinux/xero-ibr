import time
import urllib.parse
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..core.firmware import SignedIpsw, default_choice, download_status, ipsw_choices
from ..core.fmt import format_size
from ..core.ipsw_library import IpswInfo, ipsw_state, scan_folder
from ..services.firmware import download_ipsw, fetch_devices, fetch_signed
from ..services.runner import in_thread
from .widgets import button, hbox, label, set_button_text, vbox

_BADGES = {"fits": ("Fits", "ok"), "unsigned": ("Not signed", "warn"), "other": ("Other device", "muted"),
           "unknown": ("Unknown", "muted")}


def _copy(widget: Gtk.Widget, text: str):
    widget.get_clipboard().set_content(
        Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(text.encode())))


class IpswLibrary(Gtk.Box):
    """The .ipsw files in the iPSW folder, kept up to date while shown. With a model, each file gets a badge
    saying whether it fits that device; manage adds Show in folder and Delete."""

    __gsignals__ = {
        "activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, window, model: str | None = None, manage: bool = False, other_file=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        self._window = window
        self._model = model
        self._signed: set[str] | None = None
        self._selected: str | None = None
        self.files: list[IpswInfo] = []
        self._monitor = None
        self._rescan_source = 0

        heading = hbox(6, "panel-heading")
        heading.append(Gtk.Image(icon_name="folder-symbolic", css_classes=["heading-icon"]))
        title = label("IPSW LIBRARY", "section-title")
        title.set_hexpand(True)
        title.set_valign(Gtk.Align.CENTER)
        heading.append(title)
        folder = button("", "folder-open-symbolic", "outline", "compact", tooltip="Change the iPSW folder")
        folder.connect("clicked", lambda *_: self._pick_folder())
        heading.append(folder)
        if other_file:
            other = button("Other file…", None, "outline", "compact", tooltip="Use an .ipsw from somewhere else")
            other.connect("clicked", lambda *_: other_file())
            heading.append(other)
        self.append(heading)

        card = vbox(6, "card", "library")
        card.set_vexpand(True)
        self._list = Gtk.ListBox(css_classes=["library-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        empty = label("No iPSW files here yet. Download one" + (", or drop one onto this box." if other_file
                                                               else "."), "caption", wrap=True, xalign=0.5)
        empty.set_margin_top(18)
        empty.set_margin_bottom(18)
        self._list.set_placeholder(empty)
        self._list.connect("row-activated", lambda _l, row: self.emit("activated", row.info.path))
        self._list.connect("row-selected", lambda *_: self._update_actions())
        card.append(Gtk.ScrolledWindow(child=self._list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.status = label("", "caption", ellipsize=True)
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        card.append(self.status)
        self.note = label("", "caption", wrap=True)
        self.note.set_visible(False)
        card.append(self.note)
        self._actions = []
        if manage:
            actions = hbox(8)
            reveal = button("Show in Folder", "folder-open-symbolic", "outline", "compact")
            reveal.connect("clicked", lambda *_: self._reveal())
            delete = button("Delete", "user-trash-symbolic", "danger", "compact")
            delete.connect("clicked", lambda *_: self._delete())
            actions.append(reveal)
            actions.append(delete)
            card.append(actions)
            self._actions = [reveal, delete]
        if other_file:
            drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            drop.connect("drop", self._on_drop)
            card.add_controller(drop)
        self.append(card)
        self.connect("unrealize", lambda *_: self.stop())
        self.watch()

    def folder(self) -> Path:
        return Path(self._window.settings.firmware_dir)

    def watch(self):
        folder = self.folder()
        self.status.set_tooltip_text(str(folder))
        self.status.set_label(f"Folder: {folder}")
        if self._monitor:
            self._monitor.cancel()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._monitor = Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", lambda *_: self._rescan_soon())
        except (OSError, GLib.Error):
            self._monitor = None
        self.rescan()

    def stop(self):
        if self._monitor:
            self._monitor.cancel()
            self._monitor = None
        if self._rescan_source:
            GLib.source_remove(self._rescan_source)
            self._rescan_source = 0

    def _rescan_soon(self):
        if not self._rescan_source:
            self._rescan_source = GLib.timeout_add(700, self.rescan)

    def rescan(self):
        self._rescan_source = 0
        folder = self.folder()
        in_thread(lambda: scan_folder(folder), lambda files: folder == self.folder() and self._show(files))
        return False

    def set_signed(self, signed: set[str] | None):
        """Builds Apple signs for the model, to tell fitting files from ones it no longer accepts."""
        self._signed = signed
        self._show(self.files)

    def select(self, path: str | None):
        self._selected = path
        index = 0
        while (row := self._list.get_row_at_index(index)) is not None:
            if row.info.path == path:
                self._list.select_row(row)
                return
            index += 1
        self._list.unselect_all()

    def _show(self, files: list[IpswInfo]):
        self.files = files
        self._list.remove_all()
        for info in files:
            row = Gtk.ListBoxRow()
            row.info = info
            row.set_tooltip_text(info.path)
            content = hbox(8)
            content.append(Gtk.Image(icon_name="ibr-ipsw", pixel_size=24))
            title = f"{info.version} ({info.build})" if info.version else Path(info.path).name
            content.append(label(title, ellipsize=True))
            devices = info.models[0] + (f" +{len(info.models) - 1}" if len(info.models) > 1 else "") \
                if info.models else ""
            detail = label(" · ".join(p for p in (devices, format_size(info.size)) if p), "caption", ellipsize=True)
            detail.set_hexpand(True)
            content.append(detail)
            if self._model:
                text, css = _BADGES[ipsw_state(info, self._model, self._signed)]
                badge = label(text, "badge", css)
                badge.set_valign(Gtk.Align.CENTER)
                content.append(badge)
            row.set_child(content)
            self._list.append(row)
        self.select(self._selected)
        self._update_actions()
        self.emit("changed", files)

    def _current(self) -> IpswInfo | None:
        row = self._list.get_selected_row()
        return row.info if row is not None else None

    def _update_actions(self):
        for widget in self._actions:
            widget.set_sensitive(self._current() is not None)

    def _reveal(self):
        info = self._current()
        if info:
            Gtk.FileLauncher.new(Gio.File.new_for_path(info.path)).open_containing_folder(
                self.get_root(), None, None)

    def _delete(self):
        from .dialog import confirm
        info = self._current()
        if info is None:
            return
        name = Path(info.path).name

        def answered(ok):
            if not ok:
                return
            try:
                Path(info.path).unlink()
            except OSError as error:
                self.note.set_label(f"Could not delete {name}: {error.strerror or error}")
                self.note.set_visible(True)
                return
            self.rescan()

        confirm(self.get_root(), f"Delete {name}?", f"It is removed from {self.folder()} ({format_size(info.size)}).",
                "Delete", answered, destructive=True)

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = [f.get_path() for f in value.get_files() if f.get_path() and f.get_path().endswith(".ipsw")]
        if not files:
            return False
        self.emit("activated", files[0])
        return True

    def _pick_folder(self):
        dialog = Gtk.FileDialog(title="Choose iPSW folder", modal=True)
        dialog.set_initial_folder(Gio.File.new_for_path(str(self.folder())))

        def chosen(source, result):
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return
            if folder and folder.get_path():
                self._window.settings.firmware_dir = folder.get_path()
                self._window.settings.save()
                self.watch()

        dialog.select_folder(self.get_root(), None, chosen)


class IpswDownloader(Gtk.Box):
    """Device and build pickers for every iPSW Apple signs, the build's details, and a download into the
    iPSW folder with its progress. own_model and own_build describe a connected device, if any."""

    __gsignals__ = {
        "signed": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        "downloaded": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "in-library": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, window, model: str | None, model_name: str = "", own_build: str | None = None,
                 idle_text: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        self._window = window
        self._own_model = model
        self._own_build = own_build
        self._model_name = model_name
        self._models: list[tuple[str, str]] = []
        self._signed: list[SignedIpsw] = []
        self._looking_up: str | None = None
        self.downloading = False
        self._cancel = False

        heading = hbox(6, "panel-heading")
        heading.append(Gtk.Image(icon_name="folder-download-symbolic", css_classes=["heading-icon"]))
        title = label("IPSW TO DOWNLOAD", "section-title")
        title.set_valign(Gtk.Align.CENTER)
        heading.append(title)
        self.append(heading)
        card = vbox(12, "card")
        card.set_vexpand(True)
        pickers = Gtk.Grid(column_spacing=12, row_spacing=8)
        self._device_names = Gtk.StringList()
        self._devices = Gtk.DropDown(model=self._device_names, enable_search=True, hexpand=True,
                                     expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self._devices.update_property([Gtk.AccessibleProperty.LABEL], ["Device"])
        self._devices.connect("notify::selected", lambda *_: self._on_device_chosen())
        self._version_names = Gtk.StringList()
        self._versions = Gtk.DropDown(model=self._version_names, hexpand=True, sensitive=False)
        self._versions.update_property([Gtk.AccessibleProperty.LABEL], ["iPSW"])
        self._versions.connect("notify::selected", lambda *_: self.refresh())
        for row, (name, widget) in enumerate((("Device", self._devices), ("iPSW", self._versions))):
            title = label(name, "caption")
            title.set_valign(Gtk.Align.CENTER)
            pickers.attach(title, 0, row, 1, 1)
            pickers.attach(widget, 1, row, 1, 1)
        card.append(pickers)

        info = hbox(10)
        texts = vbox(2)
        texts.set_hexpand(True)
        self._name = label("", "h3", selectable=True)
        self._name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._meta = label("", "caption", wrap=True)
        texts.append(self._name)
        texts.append(self._meta)
        info.append(texts)
        self._copies = []
        for icon, tooltip, field in (("edit-copy-symbolic", "Copy file name", "filename"),
                                     ("insert-link-symbolic", "Copy Apple download link", "url")):
            copy = button("", icon, "outline", tooltip=tooltip)
            copy.set_valign(Gtk.Align.CENTER)
            copy.connect("clicked", lambda _b, f=field: self.selected() and _copy(self, getattr(self.selected(), f)))
            self._copies.append(copy)
            info.append(copy)
        self._get = button("Download…", "folder-download-symbolic", "primary")
        self._get.set_valign(Gtk.Align.CENTER)
        self._get.connect("clicked", lambda *_: self._download_selected())
        info.append(self._get)
        card.append(info)

        facts = Gtk.Grid(column_spacing=16, row_spacing=6)
        self._facts = {}
        for row, name in enumerate(("Version", "Build", "Size", "Checksum", "From")):
            facts.attach(label(name, "caption"), 0, row, 1, 1)
            value = label("–", ellipsize=True, selectable=True)
            value.set_hexpand(True)
            facts.attach(value, 1, row, 1, 1)
            self._facts[name] = value
        card.append(facts)

        self._idle = label(idle_text, "caption", wrap=True)
        self._idle.set_vexpand(True)
        self._idle.set_valign(Gtk.Align.END)
        card.append(self._idle)

        self._fetching = vbox(8, "download-progress")
        self._fetching.set_vexpand(True)
        self._fetching.set_valign(Gtk.Align.END)
        self._fetching.set_visible(False)
        top = hbox(10)
        self._fetch_title = label("", "h3", ellipsize=True)
        self._fetch_title.set_hexpand(True)
        top.append(self._fetch_title)
        self._percent = label("", "fetch-percent")
        top.append(self._percent)
        self._fetching.append(top)
        self._bar = Gtk.ProgressBar()
        self._bar.add_css_class("thick")
        self._fetching.append(self._bar)
        bottom = hbox(10)
        self._fetch_status = label("", "caption", ellipsize=True)
        self._fetch_status.set_hexpand(True)
        self._fetch_status.set_valign(Gtk.Align.CENTER)
        bottom.append(self._fetch_status)
        self._cancel_button = button("Cancel", None, "outline", "compact")
        self._cancel_button.connect("clicked", lambda *_: self.stop())
        bottom.append(self._cancel_button)
        self._fetching.append(bottom)
        card.append(self._fetching)
        self.append(card)

        start = model or window.settings.ipsw_device or None
        self._pick(start)
        fetch_devices(self._on_devices)

    def _folder(self) -> Path:
        return Path(self._window.settings.firmware_dir)

    def _pick(self, model: str | None):
        """Shows model in the list before the full list arrives, and looks up what Apple signs for it."""
        if model and model not in [m for m, _ in self._models]:
            name = self._model_name if model == self._own_model and self._model_name else model
            self._models.insert(0, (model, f"{name} ({model})" if name != model else model))
            self._device_names.splice(0, 0, [self._models[0][1]])
        if model:
            self._devices.set_selected([m for m, _ in self._models].index(model))
        else:
            self._show_lookup("Pick a device to see the iPSW Apple signs for it.")

    def _on_devices(self, devices: list[tuple[str, str]]):
        if not devices:
            return
        current = self.chosen_model()
        self._models = [(m, f"{name} ({m})") for m, name in devices]
        if current and current not in [m for m, _ in self._models]:
            self._models.insert(0, (current, f"{self._model_name or current} ({current})"))
        self._device_names.splice(0, self._device_names.get_n_items(), [name for _, name in self._models])
        self._devices.set_selected([m for m, _ in self._models].index(current) if current else 0)

    def chosen_model(self) -> str | None:
        index = self._devices.get_selected()
        return self._models[index][0] if 0 <= index < len(self._models) else None

    def _on_device_chosen(self):
        model = self.chosen_model()
        if not model or self._looking_up == model:
            return
        self._looking_up = model
        if model != self._own_model:
            self._window.settings.ipsw_device = model
            self._window.settings.save()
        self._signed = []
        self._version_names.splice(0, self._version_names.get_n_items(), [])
        self._show_lookup(f"Checking which iPSW Apple signs for {model}…")
        fetch_signed(model, lambda signed: model == self.chosen_model() and self._on_signed(model, signed))

    def _show_lookup(self, text: str):
        self._versions.set_sensitive(False)
        self._name.set_label("")
        self._meta.set_label(text)
        for value in self._facts.values():
            value.set_label("–")
        for widget in (*self._copies, self._get):
            widget.set_sensitive(False)

    def _on_signed(self, model: str, signed):
        if signed is None:
            self._show_lookup(f"Could not look up the iPSW for {model}. Check the internet connection.")
            return
        if not signed:
            self._show_lookup(f"Apple does not sign any iPSW for {model} right now.")
            return
        self._signed = signed
        build = self._own_build if model == self._own_model else None
        self._version_names.splice(0, self._version_names.get_n_items(), ipsw_choices(signed, build))
        self._versions.set_selected(default_choice(signed, build))
        self._versions.set_sensitive(len(signed) > 1 and not self.downloading)
        self.refresh()
        self.emit("signed", model, signed)

    def selected(self) -> SignedIpsw | None:
        index = self._versions.get_selected()
        return self._signed[index] if 0 <= index < len(self._signed) else None

    def select_file(self, filename: str):
        index = next((i for i, ipsw in enumerate(self._signed) if ipsw.filename == filename), None)
        if index is not None:
            self._versions.set_selected(index)

    def refresh(self):
        ipsw = self.selected()
        if ipsw is None:
            return
        self._name.set_label(ipsw.filename)
        size = f" · {format_size(ipsw.size)}" if ipsw.size else ""
        self._meta.set_label(f"{ipsw.version} ({ipsw.build}){size}")
        self._facts["Version"].set_label(ipsw.version)
        self._facts["Build"].set_label(ipsw.build)
        self._facts["Size"].set_label(format_size(ipsw.size) if ipsw.size else "Unknown")
        self._facts["Checksum"].set_label(f"SHA-256 {ipsw.sha256[:16]}…" if ipsw.sha256 else "Not published")
        self._facts["From"].set_label(urllib.parse.urlsplit(ipsw.url).hostname or "Apple")
        have = (self._folder() / ipsw.filename).exists()
        set_button_text(self._get, "In library" if have else "Download…")
        for widget in self._copies:
            widget.set_sensitive(not self.downloading)
        self._get.set_sensitive(not self.downloading and not have)

    def _download_selected(self):
        ipsw = self.selected()
        if ipsw is None:
            return
        target = self._folder() / ipsw.filename
        if target.exists():
            self.emit("in-library", str(target))
            return
        self._start(ipsw, target)

    def _start(self, ipsw: SignedIpsw, target: Path):
        self._cancel = False
        self.downloading = True
        self._fetch_title.set_label(f"Downloading {ipsw.version} ({ipsw.build})")
        self._percent.set_label("0%")
        self._bar.set_fraction(0)
        self._fetch_status.set_label("Starting…")
        self._cancel_button.set_visible(True)
        self._cancel_button.set_sensitive(True)
        self._fetching.set_visible(True)
        self._idle.set_visible(False)
        for widget in (*self._copies, self._get, self._devices, self._versions):
            widget.set_sensitive(False)
        meter = {"time": time.monotonic(), "done": 0, "speed": 0.0, "shown": 0.0}

        def progress(done: int, total: int | None):
            now = time.monotonic()
            if now - meter["time"] >= 0.5:
                rate = (done - meter["done"]) / (now - meter["time"])
                meter["speed"] = rate if not meter["speed"] else meter["speed"] * 0.7 + rate * 0.3
                meter["time"], meter["done"] = now, done
            if now - meter["shown"] >= 0.25 or done == total:
                meter["shown"] = now
                GLib.idle_add(self._show_progress, done, total or ipsw.size, meter["speed"])

        def work():
            return download_ipsw(ipsw.url, target, ipsw.sha256, progress, lambda: self._cancel)

        in_thread(work, lambda error: self._finished(target, error))

    def _show_progress(self, done: int, total: int | None, speed: float):
        if total:
            self._bar.set_fraction(min(done / total, 1.0))
            self._percent.set_label(f"{done * 100 // total}%")
        self._fetch_status.set_label(download_status(done, total, speed))
        return False

    def stop(self):
        """Cancels a running download; nothing is left behind."""
        if not self.downloading:
            return
        self._cancel = True
        self._cancel_button.set_sensitive(False)
        self._fetch_status.set_label("Cancelling…")

    def _finished(self, target: Path, error: str | None):
        self.downloading = False
        self._devices.set_sensitive(True)
        self._versions.set_sensitive(len(self._signed) > 1)
        self._cancel_button.set_visible(False)
        self.refresh()
        if error:
            self._fetching.set_visible(error != "Cancelled")
            self._idle.set_visible(error == "Cancelled")
            self._fetch_title.set_label("Download stopped")
            self._percent.set_label("")
            self._fetch_status.set_label(error)
            return
        self._fetch_title.set_label("Downloaded")
        self._percent.set_label("100%")
        self._bar.set_fraction(1.0)
        self._fetch_status.set_label(f"Saved to {target}")
        self.emit("downloaded", str(target))
