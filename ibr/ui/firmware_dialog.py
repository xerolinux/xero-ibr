import time
from pathlib import Path

from gi.repository import Gio, GLib, Gtk

from ..core.commands import firmware_cmd
from ..core.firmware import (STEP_NAMES, FirmwareParser, FirmwareTarget, OverallPercent, SignedIpsw, StepChanged,
                             ipsw_matches)
from ..core.fmt import format_size
from ..core.ipsw_library import best_for
from ..core.progress import Error
from ..core.settings import xdg_dir
from ..core.support import MIN_OS_LABEL
from ..services.firmware import check_tool
from ..services.operation import Operation
from .device_art import DeviceArt
from .dialog import Dialog, confirm
from .ipsw_panels import IpswDownloader, IpswLibrary
from .widgets import button, clear, hbox, label, set_classes, vbox

# Wider and taller than other dialogs: two columns of controls plus the iPSW library. Still inside the main window.
FIRMWARE_PANEL = (1040, 680)


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
        self._tool = None
        self._operation = None
        self._pulse = 0
        self._seen: set[int] = set()
        self._started = 0.0
        self._erasing = False
        self._own_signed: set[str] | None = None
        self._chosen_by_user = False
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
        self._downloader.stop()
        self._library.stop()
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

        self._library = IpswLibrary(self._window, self._device.product_type, other_file=self._choose_file)
        self._library.connect("activated", lambda _l, path: self._use_file(path, chosen=True))
        self._library.connect("changed", lambda _l, files: self._auto_pick())
        left.append(self._library)
        page.append(left)

        self._downloader = IpswDownloader(
            self._window, self._device.product_type, self._device.spec.name, self._device.build,
            "It is saved to your iPSW library and checked against Apple's checksum. A file for this device is "
            "picked to install.")
        self._downloader.set_hexpand(True)
        self._downloader.connect("signed", self._on_signed)
        self._downloader.connect("downloaded", lambda _d, path: self._window.ipsw_downloaded(path))
        self._downloader.connect("in-library", lambda _d, path: self._use_file(path, chosen=True))
        page.append(self._downloader)

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
        self._refresh()
        return outer

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

    def _on_tool(self, state: str):
        self._tool = state
        self._refresh()

    def _on_signed(self, _downloader, model: str, signed: list[SignedIpsw]):
        if model == self._device.product_type:
            self._own_signed = {ipsw.build for ipsw in signed}
            self._library.set_signed(self._own_signed)
            self._auto_pick()

    def _auto_pick(self):
        """Until someone picks a file, the newest one Apple signs for this device is used."""
        model = self._device.product_type
        if self._chosen_by_user or not model:
            self._refresh()
            return
        best = best_for(self._library.files, model, self._own_signed)
        if best and best.path != self._ipsw:
            self._use_file(best.path)
        else:
            self._refresh()

    def take_download(self, path: str):
        """A new iPSW in the library, from this window or the iPSW Manager: used when it is for this device."""
        model = self._device.product_type
        if model and ipsw_matches(Path(path).name, model):
            self._use_file(path, chosen=True)
        self._library.rescan()

    def _use_file(self, path: str, chosen: bool = False):
        self._ipsw = path
        self._chosen_by_user = self._chosen_by_user or chosen
        self._library.select(path)
        self._downloader.select_file(Path(path).name)
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
        status, note, folder = self._library.status, self._library.note, self._library.folder()
        if not self._ipsw:
            status.set_label(f"Folder: {folder}")
            note.set_visible(False)
            return False
        path = Path(self._ipsw)
        size = path.stat().st_size if path.is_file() else 0
        status.set_label(f"Using {path} · {format_size(size)}" if path.parent != folder else f"Folder: {folder}")
        model = self._device.product_type
        info = next((f for f in self._library.files if f.path == str(path) and f.models), None)
        match = (model in info.models if info else ipsw_matches(path.name, model)) if model else None
        note.set_visible(match is not True)
        if match is False:
            note.set_label(f"This file is not for {model}. Choose the firmware for this model.")
            set_classes(note, "device-status", "warn", keep=("caption",))
            return False
        if match is None:
            note.set_label(f"The file name does not say which model it is for. Make sure it is for "
                           f"{model or 'this device'}.")
            set_classes(note, keep=("caption",))
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
