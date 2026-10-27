import time
import urllib.parse
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from ..core.commands import firmware_cmd
from ..core.firmware import (STEP_NAMES, FirmwareParser, FirmwareTarget, OverallPercent, SignedIpsw, StepChanged,
                             default_choice, download_status, ipsw_choices, ipsw_matches)
from ..core.fmt import format_size
from ..core.ipsw_library import IpswInfo, best_for, ipsw_state, scan_folder
from ..core.progress import Error
from ..core.settings import xdg_dir
from ..core.support import MIN_OS_LABEL
from ..services.firmware import check_tool, download_ipsw, fetch_devices, fetch_signed
from ..services.operation import Operation
from ..services.runner import in_thread
from .device_art import DeviceArt
from .dialog import Dialog, confirm
from .widgets import button, clear, hbox, label, set_button_text, set_classes, vbox

# Wider and taller than other dialogs: two columns of controls plus the iPSW library. Still inside the main window.
FIRMWARE_PANEL = (1040, 680)
_BADGES = {"fits": ("Fits", "ok"), "unsigned": ("Not signed", "warn"), "other": ("Other device", "muted"),
           "unknown": ("Unknown", "muted")}


TOOL_HELP = {
    "missing": "Firmware updates need idevicerestore. On Arch install idevicerestore-git from the AUR; "
               "the AppImage already includes it.",
    "old": f"The installed idevicerestore is too old for {MIN_OS_LABEL} and later. Install a current build "
           "(idevicerestore-git on Arch) or use the AppImage.",
}


class FirmwareDialog(Dialog):
    def __init__(self, window, device: FirmwareTarget):
        self._os = device.os_name
        super().__init__(window, f"Update or Restore {self._os} on {device.name}", *FIRMWARE_PANEL)
        self._window = window
        self._device = device
        self._ipsw: str | None = None
        self._signed = []
        self._tool = None
        self._operation = None
        self._pulse = 0
        self._seen: set[int] = set()
        self._started = 0.0
        self._erasing = False
        self._cancel_download = False
        self._looking_up: str | None = None
        self._files: list[IpswInfo] = []
        self._own_signed: set[str] | None = None
        self._chosen_by_user = False
        self._downloading = False
        self._monitor = None
        self._rescan_source = 0
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.add_named(self._choose_page(), "choose")
        self._stack.add_named(self._progress_page(), "progress")
        self._stack.add_named(self._result_page(), "result")
        self.set_child(self._stack)
        self.connect("close-request", self._on_close)
        check_tool(self._on_tool)

    def _on_close(self, *_):
        if self._operation and self._operation.running:
            return True
        self._cancel_download = True
        if self._monitor:
            self._monitor.cancel()
        if self._rescan_source:
            GLib.source_remove(self._rescan_source)
            self._rescan_source = 0
        return False

    def _margins(self, box: Gtk.Box, value: int = 24):
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(value)

    def _choose_page(self):
        body = vbox(16)
        self._margins(body, 20)
        notice = hbox(12, "warning-box")
        icon = Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=20)
        icon.set_valign(Gtk.Align.CENTER)
        notice.append(icon)
        self._warning = label("", "warning-text", wrap=True)
        self._warning.set_hexpand(True)
        self._warning.set_valign(Gtk.Align.CENTER)
        notice.append(self._warning)
        self._ack = Gtk.CheckButton()
        self._ack.set_valign(Gtk.Align.CENTER)
        self._ack.connect("toggled", lambda *_: self._refresh())
        notice.append(self._ack)
        body.append(notice)
        page = hbox(20)
        page.set_homogeneous(True)
        page.set_vexpand(True)
        body.append(page)
        left = vbox(12)
        spec = self._device.spec
        status = hbox(12, "card")
        status.append(Gtk.Image.new_from_icon_name("software-update-available-symbolic"))
        texts = vbox(2)
        build = f" ({self._device.build})" if self._device.build else ""
        texts.append(label(f"Installed: {self._device.installed}{build}", "h3", wrap=True))
        texts.append(label(f"{spec.name} · {self._device.product_type or 'unknown model'}", "caption"))
        status.append(texts)
        left.append(status)

        left.append(label("WHAT TO DO", "section-title"))
        choices = Gtk.Grid(column_spacing=10, column_homogeneous=True)
        self._update = Gtk.CheckButton(label="Update: keep data", active=True)
        self._erase = Gtk.CheckButton(label="Restore: erase all", group=self._update)
        self._erase.connect("toggled", lambda *_: self._refresh())
        for column, choice in enumerate((self._update, self._erase)):
            choice.add_css_class("choice-card")
            choices.attach(choice, column, 0, 1, 1)
        left.append(choices)

        heading = hbox(6)
        title = label("IPSW LIBRARY", "section-title")
        title.set_hexpand(True)
        title.set_valign(Gtk.Align.CENTER)
        heading.append(title)
        folder = button("", "folder-open-symbolic", "outline", "compact", tooltip="Change the iPSW folder")
        folder.connect("clicked", lambda *_: self._pick_library_folder())
        other = button("Other file…", None, "outline", "compact", tooltip="Use an .ipsw from somewhere else")
        other.connect("clicked", lambda *_: self._choose_file())
        heading.append(folder)
        heading.append(other)
        left.append(heading)
        left.append(self._library_card())
        page.append(left)

        right = vbox(12)
        right.set_hexpand(True)
        right.append(label("IPSW TO DOWNLOAD", "section-title"))
        right.append(self._download_card())
        page.append(right)

        footer = hbox(16)
        footer.set_margin_start(20)
        footer.set_margin_end(20)
        footer.set_margin_bottom(20)
        note = label("Apple only installs versions it still signs. If the device restarts into recovery mode and "
                     "is not found, add libirecovery's udev rules.", "caption", wrap=True)
        note.set_hexpand(True)
        footer.append(note)
        self._start = button("Update", None, "primary", "big")
        self._start.set_valign(Gtk.Align.CENTER)
        self._start.connect("clicked", self._on_start)
        footer.append(self._start)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(body)
        outer = vbox(0)
        outer.append(scroller)
        outer.append(footer)
        self._pick_device(self._device.product_type)
        fetch_devices(self._on_devices)
        self._watch_library()
        self._refresh()
        return outer

    def _library_card(self) -> Gtk.Widget:
        card = vbox(6, "card", "library")
        card.set_vexpand(True)
        self._library = Gtk.ListBox(css_classes=["library-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        empty = label("No iPSW files here yet. Download one, or drop one onto this box.", "caption", wrap=True,
                      xalign=0.5)
        empty.set_margin_top(18)
        empty.set_margin_bottom(18)
        self._library.set_placeholder(empty)
        self._library.connect("row-activated", lambda _l, row: self._use_file(row.info.path, chosen=True))
        card.append(Gtk.ScrolledWindow(child=self._library, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self._ipsw_label = label("", "caption", ellipsize=True)
        self._ipsw_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        card.append(self._ipsw_label)
        self._match = label("", "caption", wrap=True)
        self._match.set_visible(False)
        card.append(self._match)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        card.add_controller(drop)
        return card

    def _library_folder(self) -> Path:
        return Path(self._window.settings.firmware_dir)

    def _watch_library(self):
        folder = self._library_folder()
        self._ipsw_label.set_tooltip_text(str(folder))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._monitor = Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", lambda *_: self._rescan_soon())
        except (OSError, GLib.Error):
            self._monitor = None
        self._rescan()

    def _rescan_soon(self):
        if not self._rescan_source:
            self._rescan_source = GLib.timeout_add(700, self._rescan)

    def _rescan(self):
        self._rescan_source = 0
        folder = self._library_folder()
        in_thread(lambda: scan_folder(folder),
                  lambda files: folder == self._library_folder() and self._on_library(files))
        return False

    def _on_library(self, files: list[IpswInfo]):
        self._files = files
        model = self._device.product_type
        signed = self._own_signed
        self._library.remove_all()
        for info in files:
            row = Gtk.ListBoxRow()
            row.info = info
            row.set_tooltip_text(info.path)
            content = hbox(8)
            title = f"{info.version} ({info.build})" if info.version else Path(info.path).name
            content.append(label(title, ellipsize=True))
            devices = info.models[0] + (f" +{len(info.models) - 1}" if len(info.models) > 1 else "") \
                if info.models else ""
            detail = label(" · ".join(p for p in (devices, format_size(info.size)) if p), "caption", ellipsize=True)
            detail.set_hexpand(True)
            content.append(detail)
            state = ipsw_state(info, model, signed) if model else "unknown"
            text, css = _BADGES[state]
            badge = label(text, "badge", css)
            badge.set_valign(Gtk.Align.CENTER)
            content.append(badge)
            row.set_child(content)
            self._library.append(row)
        self._select_library_row()
        self._show_ipsw()
        if not self._chosen_by_user and model:
            best = best_for(files, model, signed)
            if best and best.path != self._ipsw:
                self._use_file(best.path)

    def _select_library_row(self):
        index = 0
        while (row := self._library.get_row_at_index(index)) is not None:
            if row.info.path == self._ipsw:
                self._library.select_row(row)
                return
            index += 1
        self._library.unselect_all()

    def _pick_library_folder(self):
        dialog = Gtk.FileDialog(title="Choose iPSW folder", modal=True)
        dialog.set_initial_folder(Gio.File.new_for_path(str(self._library_folder())))

        def chosen(source, result):
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return
            if folder and folder.get_path():
                self._window.settings.firmware_dir = folder.get_path()
                self._window.settings.save()
                self._watch_library()

        dialog.select_folder(self, None, chosen)

    def _download_card(self) -> Gtk.Widget:
        card = vbox(12, "card")
        card.set_vexpand(True)
        pickers = Gtk.Grid(column_spacing=12, row_spacing=8)
        self._models: list[tuple[str, str]] = []
        self._device_names = Gtk.StringList()
        self._devices = Gtk.DropDown(model=self._device_names, enable_search=True, hexpand=True,
                                     expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self._devices.update_property([Gtk.AccessibleProperty.LABEL], ["Device"])
        self._devices.connect("notify::selected", lambda *_: self._on_device_chosen())
        self._version_names = Gtk.StringList()
        self._versions = Gtk.DropDown(model=self._version_names, hexpand=True, sensitive=False)
        self._versions.update_property([Gtk.AccessibleProperty.LABEL], ["iPSW"])
        self._versions.connect("notify::selected", lambda *_: self._show_ipsw())
        for row, (name, widget) in enumerate((("Device", self._devices), ("iPSW", self._versions))):
            title = label(name, "caption")
            title.set_valign(Gtk.Align.CENTER)
            pickers.attach(title, 0, row, 1, 1)
            pickers.attach(widget, 1, row, 1, 1)
        card.append(pickers)

        info = hbox(10)
        texts = vbox(2)
        texts.set_hexpand(True)
        self._ipsw_name = label("", "h3", selectable=True)
        self._ipsw_name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._ipsw_meta = label("", "caption", wrap=True)
        texts.append(self._ipsw_name)
        texts.append(self._ipsw_meta)
        info.append(texts)
        self._copies = []
        for icon, tooltip, field in (("edit-copy-symbolic", "Copy file name", "filename"),
                                     ("insert-link-symbolic", "Copy Apple download link", "url")):
            copy = button("", icon, "outline", tooltip=tooltip)
            copy.set_valign(Gtk.Align.CENTER)
            copy.connect("clicked", lambda _b, f=field: self._copy(getattr(self._selected_ipsw(), f)))
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

        self._fetch_idle = label("It is saved to your iPSW library and checked against Apple's checksum. A file "
                                 "for this device is picked to install.", "caption", wrap=True)
        self._fetch_idle.set_vexpand(True)
        self._fetch_idle.set_valign(Gtk.Align.END)
        card.append(self._fetch_idle)

        self._fetching = vbox(8, "download-progress")
        self._fetching.set_vexpand(True)
        self._fetching.set_valign(Gtk.Align.END)
        self._fetching.set_visible(False)
        top = hbox(10)
        self._fetch_title = label("", "h3", ellipsize=True)
        self._fetch_title.set_hexpand(True)
        top.append(self._fetch_title)
        self._fetch_percent = label("", "fetch-percent")
        top.append(self._fetch_percent)
        self._fetching.append(top)
        self._fetch_bar = Gtk.ProgressBar()
        self._fetch_bar.add_css_class("thick")
        self._fetching.append(self._fetch_bar)
        bottom = hbox(10)
        self._fetch_status = label("", "caption", ellipsize=True)
        self._fetch_status.set_hexpand(True)
        self._fetch_status.set_valign(Gtk.Align.CENTER)
        bottom.append(self._fetch_status)
        self._fetch_cancel = button("Cancel", None, "outline", "compact")
        self._fetch_cancel.connect("clicked", lambda *_: self._stop_download())
        bottom.append(self._fetch_cancel)
        self._fetching.append(bottom)
        card.append(self._fetching)
        return card

    def _art(self) -> DeviceArt:
        art = DeviceArt(240, 330)
        art.set_device(self._device.spec, product_type=self._device.product_type)
        art.set_valign(Gtk.Align.CENTER)
        return art

    def _progress_page(self):
        page = hbox(40)
        self._margins(page, 32)
        page.append(self._art())
        column = vbox(16)
        column.set_hexpand(True)
        column.set_valign(Gtk.Align.CENTER)
        self._progress_title = label("", "h2")
        column.append(self._progress_title)
        card = vbox(12, "progress-card")
        top = hbox(12)
        self._step = label("Starting", "h3", ellipsize=True)
        self._step.set_hexpand(True)
        top.append(self._step)
        self._percent = label("", "big-percent")
        top.append(self._percent)
        card.append(top)
        self._bar = Gtk.ProgressBar()
        self._bar.add_css_class("thick")
        card.append(self._bar)
        self._detail = label("", "caption", ellipsize=True)
        self._detail.set_visible(False)
        card.append(self._detail)
        column.append(card)
        self._stage_rows = []
        stages = vbox(8)
        for name in STEP_NAMES:
            row = label(name, "step")
            self._stage_rows.append(row)
            stages.append(row)
        column.append(stages)
        column.append(label("Keep the device plugged in. It restarts several times; do not unplug it until "
                            "this window says it is finished.", "caption", wrap=True))
        page.append(column)
        return page

    def _show_stage(self, current: int):
        """idevicerestore skips and reorders steps by device, so a step is done once a later one has started."""
        if current < 0:
            self._seen = set()
        else:
            self._seen.add(current)
        for index, row in enumerate(self._stage_rows):
            done, now = index in self._seen and index != current, index == current
            name = STEP_NAMES[index]
            row.set_label(f"✓ {name}" if done else f"● {name}" if now else name)
            set_classes(row, *(["done"] if done else ["current"] if now else []), keep=("step",))

    def _result_page(self):
        page = hbox(40)
        self._margins(page, 32)
        page.append(self._art())
        column = vbox(14)
        column.set_hexpand(True)
        column.set_valign(Gtk.Align.CENTER)
        self._result_icon = Gtk.Image(pixel_size=48)
        self._result_icon.set_halign(Gtk.Align.START)
        self._result_title = label("", "h2")
        self._result_text = label("", "body-text", wrap=True)
        self._result_facts = vbox(6, "card")
        close = button("Close", None, "primary", "big")
        close.set_halign(Gtk.Align.START)
        close.connect("clicked", lambda *_: self.close())
        for widget in (self._result_icon, self._result_title, self._result_text, self._result_facts, close):
            column.append(widget)
        page.append(column)
        return page

    def _pick_device(self, model: str | None):
        """Shows model in the Device list (before the full list arrives) and looks up what Apple signs for it."""
        if model and model not in [m for m, _ in self._models]:
            self._models.insert(0, (model, f"{self._device.spec.name} ({model})"))
            self._device_names.splice(0, 0, [self._models[0][1]])
        if model:
            self._devices.set_selected([m for m, _ in self._models].index(model))
        else:
            self._show_lookup("The device did not report its model. Pick it from the Device list.")

    def _on_devices(self, devices: list[tuple[str, str]]):
        if not devices:
            return
        current = self._chosen_model()
        self._models = [(m, f"{name} ({m})") for m, name in devices]
        if current and current not in [m for m, _ in self._models]:
            self._models.insert(0, (current, f"{self._device.spec.name} ({current})"))
        self._device_names.splice(0, self._device_names.get_n_items(), [name for _, name in self._models])
        if current:
            self._devices.set_selected([m for m, _ in self._models].index(current))

    def _chosen_model(self) -> str | None:
        index = self._devices.get_selected()
        return self._models[index][0] if 0 <= index < len(self._models) else None

    def _on_device_chosen(self):
        model = self._chosen_model()
        if not model or self._looking_up == model:
            return
        self._looking_up = model
        self._signed = []
        self._version_names.splice(0, self._version_names.get_n_items(), [])
        self._show_lookup(f"Checking which iPSW Apple signs for {model}…")
        fetch_signed(model, lambda signed: model == self._chosen_model() and self._on_signed(model, signed))

    def _show_lookup(self, text: str):
        self._versions.set_sensitive(False)
        self._ipsw_name.set_label("")
        self._ipsw_meta.set_label(text)
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
        own = model == self._device.product_type
        if own:
            self._own_signed = {ipsw.build for ipsw in signed}
            self._on_library(self._files)
        self._version_names.splice(0, self._version_names.get_n_items(),
                                   ipsw_choices(signed, self._device.build if own else None))
        self._versions.set_selected(default_choice(signed, self._device.build if own else None))
        self._versions.set_sensitive(len(signed) > 1)
        self._show_ipsw()

    def _selected_ipsw(self) -> SignedIpsw | None:
        index = self._versions.get_selected()
        return self._signed[index] if 0 <= index < len(self._signed) else None

    def _show_ipsw(self):
        ipsw = self._selected_ipsw()
        if ipsw is None:
            return
        self._ipsw_name.set_label(ipsw.filename)
        size = f" · {format_size(ipsw.size)}" if ipsw.size else ""
        self._ipsw_meta.set_label(f"{ipsw.version} ({ipsw.build}){size}")
        self._facts["Version"].set_label(ipsw.version)
        self._facts["Build"].set_label(ipsw.build)
        self._facts["Size"].set_label(format_size(ipsw.size) if ipsw.size else "Unknown")
        self._facts["Checksum"].set_label(f"SHA-256 {ipsw.sha256[:16]}…" if ipsw.sha256 else "Not published")
        self._facts["From"].set_label(urllib.parse.urlsplit(ipsw.url).hostname or "Apple")
        have = (self._library_folder() / ipsw.filename).exists()
        set_button_text(self._get, "In library" if have else "Download…")
        for widget in self._copies:
            widget.set_sensitive(not self._downloading)
        self._get.set_sensitive(not self._downloading and not have)

    def _download_selected(self):
        ipsw = self._selected_ipsw()
        if ipsw is None:
            return
        target = self._library_folder() / ipsw.filename
        if target.exists():
            self._use_file(str(target), chosen=True)
            return
        self._start_download(ipsw, target)

    def _start_download(self, ipsw: SignedIpsw, target: Path):
        self._cancel_download = False
        self._downloading = True
        self._fetch_title.set_label(f"Downloading {ipsw.version} ({ipsw.build})")
        self._fetch_percent.set_label("0%")
        self._fetch_bar.set_fraction(0)
        self._fetch_status.set_label("Starting…")
        self._fetch_cancel.set_visible(True)
        self._fetching.set_visible(True)
        self._fetch_idle.set_visible(False)
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
                GLib.idle_add(self._show_download, done, total or ipsw.size, meter["speed"])

        def work():
            return download_ipsw(ipsw.url, target, ipsw.sha256, progress, lambda: self._cancel_download)

        in_thread(work, lambda error: self._download_finished(target, error))

    def _show_download(self, done: int, total: int | None, speed: float):
        if total:
            self._fetch_bar.set_fraction(min(done / total, 1.0))
            self._fetch_percent.set_label(f"{done * 100 // total}%")
        self._fetch_status.set_label(download_status(done, total, speed))
        return False

    def _stop_download(self):
        self._cancel_download = True
        self._fetch_cancel.set_sensitive(False)
        self._fetch_status.set_label("Cancelling…")

    def _download_finished(self, target: Path, error: str | None):
        self._downloading = False
        self._fetch_cancel.set_sensitive(True)
        self._devices.set_sensitive(True)
        self._versions.set_sensitive(len(self._signed) > 1)
        self._show_ipsw()
        if error:
            self._fetching.set_visible(error != "Cancelled")
            self._fetch_idle.set_visible(error == "Cancelled")
            self._fetch_title.set_label("Download stopped")
            self._fetch_percent.set_label("")
            self._fetch_status.set_label(error)
            self._fetch_cancel.set_visible(False)
            return
        self._fetch_title.set_label("Downloaded")
        self._fetch_percent.set_label("100%")
        self._fetch_bar.set_fraction(1.0)
        self._fetch_status.set_label(f"Saved to {target}")
        self._fetch_cancel.set_visible(False)
        model = self._device.product_type
        if model and ipsw_matches(target.name, model):
            self._use_file(str(target), chosen=True)
        self._rescan()

    def _copy(self, text: str):
        self.get_clipboard().set_content(
            Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(text.encode())))

    def _on_tool(self, state: str):
        self._tool = state
        self._refresh()

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = [f.get_path() for f in value.get_files() if f.get_path() and f.get_path().endswith(".ipsw")]
        if not files:
            return False
        self._use_file(files[0], chosen=True)
        return True

    def _use_file(self, path: str, chosen: bool = False):
        self._ipsw = path
        self._chosen_by_user = self._chosen_by_user or chosen
        name = Path(path).name
        match = next((i for i, ipsw in enumerate(self._signed) if ipsw.filename == name), None)
        if match is not None:
            self._versions.set_selected(match)
        self._select_library_row()
        self._refresh()

    def _choose_file(self):
        dialog = Gtk.FileDialog(title="Choose an .ipsw file", modal=True)
        only_ipsw = Gtk.FileFilter(name="Apple firmware (.ipsw)")
        only_ipsw.add_suffix("ipsw")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(only_ipsw)
        dialog.set_filters(filters)
        dialog.set_default_filter(only_ipsw)

        def chosen(source, result):
            try:
                path = source.open_finish(result).get_path()
            except GLib.Error:
                return
            if path:
                self._use_file(path, chosen=True)

        dialog.open(self, None, chosen)

    def _file_ok(self) -> bool:
        if not self._ipsw:
            self._ipsw_label.set_label(f"Folder: {self._library_folder()}")
            self._match.set_visible(False)
            return False
        path = Path(self._ipsw)
        size = path.stat().st_size if path.is_file() else 0
        outside = path.parent != self._library_folder()
        self._ipsw_label.set_label(f"Using {path} · {format_size(size)}" if outside
                                   else f"Folder: {self._library_folder()}")
        model = self._device.product_type
        info = next((f for f in self._files if f.path == str(path) and f.models), None)
        match = (model in info.models if info else ipsw_matches(path.name, model)) if model else None
        self._match.set_visible(match is not True)
        if match is False:
            self._match.set_label(f"This file is not for {self._device.product_type}. Choose the firmware for this "
                                  "model.")
            set_classes(self._match, "device-status", "warn", keep=("caption",))
            return False
        if match is None:
            self._match.set_label(f"The file name does not say which model it is for. Make sure it is for "
                                  f"{self._device.product_type or 'this device'}.")
            set_classes(self._match, keep=("caption",))
        return True

    def _refresh(self):
        erase = self._erase.get_active()
        name = self._device.name
        if self._tool in TOOL_HELP:
            self._warning.set_label(TOOL_HELP[self._tool])
        elif erase:
            self._warning.set_label(f"Restore erases everything on {name}, and it asks for its Apple ID afterwards. "
                                    "Back it up first.")
        else:
            self._warning.set_label(f"Back up {name} first. An interrupted update can leave it in recovery mode.")
        self._ack.set_label("I understand" if erase else "I have a recent backup")
        file_ok = self._file_ok()
        self._start.set_label("Erase and Restore" if erase else "Update")
        set_classes(self._start, "danger-solid" if erase else "primary", keep=("big",))
        self._start.set_sensitive(self._tool == "ok" and self._ack.get_active() and file_ok)

    def _on_start(self, *_):
        erase = self._erase.get_active()
        heading = f"Erase {self._device.name}?" if erase else f"Update {self._device.name}?"
        body = (f"All data is removed and {Path(self._ipsw).name} is installed." if erase
                else f"{Path(self._ipsw).name} is installed and your data is kept.")
        confirm(self, heading, body, "Erase and Restore" if erase else "Update",
                lambda ok: ok and self._run(erase), destructive=erase)

    def _run(self, erase: bool):
        cache = xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "firmware"
        cache.mkdir(parents=True, exist_ok=True)
        argv, env = firmware_cmd(self._device.udid, erase, self._ipsw, str(cache), ecid=self._device.ecid)
        self._operation = Operation("firmware", argv, env, FirmwareParser())
        self._operation.connect("event", self._on_event)
        self._operation.connect("done", self._on_done)
        self._progress_title.set_label(("Restoring " if erase else "Updating ") + self._device.name)
        self._erasing = erase
        self._started = time.monotonic()
        self._show_stage(-1)
        self._bar.set_fraction(0)
        self._pulse = GLib.timeout_add(120, lambda: self._bar.pulse() or True)
        self._stack.set_visible_child_name("progress")
        self.set_deletable(False)
        self._window.begin_operation(f"Updating {self._os}")
        self._operation.start()

    def _stop_pulse(self):
        if self._pulse:
            GLib.source_remove(self._pulse)
            self._pulse = 0

    def _on_event(self, operation, event):
        if isinstance(event, StepChanged):
            self._step.set_label(event.name)
            self._show_stage(event.index)
        elif isinstance(event, OverallPercent):
            self._stop_pulse()
            self._bar.set_fraction(event.value / 100)
            self._percent.set_label(f"{event.value:.0f}%")
        elif isinstance(event, Error):
            self._detail.set_label(event.message)
            self._detail.set_visible(True)

    def _on_done(self, operation, success: bool, message: str):
        self._stop_pulse()
        self._window.end_operation()
        self.set_deletable(True)
        self._result_icon.set_from_icon_name("object-select-symbolic" if success else "dialog-warning-symbolic")
        set_classes(self._result_icon, *([] if success else ["fail"]), keep=("result-icon",))
        if success:
            self._result_title.set_label("Finished")
            self._result_text.set_label(f"{self._device.name} is restarting with the new {self._os}. Unlock it to "
                                        "finish setting up.")
        else:
            self._result_title.set_label("The update did not finish")
            self._result_text.set_label(f"{message}\n\nIf the device shows a recovery screen, run this again "
                                        "with Restore. Logs are in Settings > Advanced.")
        clear(self._result_facts)
        minutes = max(1, round((time.monotonic() - self._started) / 60))
        for name, value in (("Firmware", Path(self._ipsw).name), ("Mode", "Restore" if self._erasing else "Update"),
                            ("Time taken", f"{minutes} min")):
            row = hbox(12)
            key = label(name, "caption")
            key.set_size_request(90, -1)
            row.append(key)
            row.append(label(value, ellipsize=True))
            self._result_facts.append(row)
        self._window.notify_done(f"{self._os} update finished" if success else f"{self._os} update failed",
                                 self._device.name)
        self._stack.set_visible_child_name("result")
