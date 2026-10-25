from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core.commands import firmware_cmd
from ..core.firmware import FirmwareParser, FirmwareTarget, OverallPercent, StepChanged, ipsw_matches
from ..core.fmt import format_size
from ..core.progress import Error
from ..core.settings import xdg_dir
from ..core.support import MIN_OS_LABEL
from ..services.firmware import check_tool
from ..services.operation import Operation
from .dialog import Dialog, confirm
from .widgets import button, hbox, label, set_classes, vbox

TOOL_HELP = {
    "missing": "Firmware updates need idevicerestore. On Arch install idevicerestore-git from the AUR; "
               "the AppImage already includes it.",
    "old": f"The installed idevicerestore is too old for {MIN_OS_LABEL} and later. Install a current build "
           "(idevicerestore-git on Arch) or use the AppImage.",
}


class FirmwareDialog(Dialog):
    def __init__(self, window, device: FirmwareTarget):
        self._os = device.os_name
        super().__init__(window, f"Update or Restore {self._os} on {device.name}", 680)
        self._window = window
        self._device = device
        self._ipsw: str | None = None
        self._tool = None
        self._operation = None
        self._pulse = 0
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.add_named(self._choose_page(), "choose")
        self._stack.add_named(self._progress_page(), "progress")
        self._stack.add_named(self._result_page(), "result")
        self.set_child(self._stack)
        self.connect("close-request", lambda *_: bool(self._operation and self._operation.running))
        check_tool(self._on_tool)

    def _margins(self, box: Gtk.Box, value: int = 24):
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(value)

    def _choose_page(self):
        page = vbox(16)
        self._margins(page)
        spec = self._device.spec
        status = hbox(12, "card")
        status.append(Gtk.Image.new_from_icon_name("software-update-available-symbolic"))
        texts = vbox(2)
        texts.append(label(f"Installed: {self._device.installed}", "h3"))
        texts.append(label(f"{spec.name} · model identifier {self._device.product_type or 'unknown'}", "caption"))
        status.append(texts)
        page.append(status)

        model = self._device.product_type or "<model>"
        guide = hbox(12, "card")
        required = vbox(4)
        required.set_hexpand(True)
        required.append(label("Required iPSW for this device is", "caption"))
        required.append(label(f"{model}_<version>_<build>_Restore.ipsw", "h3", wrap=True))
        guide.append(required)
        copy = button("", "edit-copy-symbolic", "outline", tooltip=f"Copy {model}")
        copy.set_valign(Gtk.Align.CENTER)
        copy.connect("clicked", lambda *_: self.get_clipboard().set_content(
            Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(model.encode()))))
        guide.append(copy)
        page.append(guide)

        page.append(label("FIRMWARE FILE", "section-title"))
        chooser = hbox(12)
        pick = button("Choose .ipsw File…", "document-open-symbolic", "outline")
        pick.connect("clicked", lambda *_: self._choose_file())
        chooser.append(pick)
        self._ipsw_label = label("No file chosen", "caption", ellipsize=True)
        self._ipsw_label.set_hexpand(True)
        self._ipsw_label.set_valign(Gtk.Align.CENTER)
        chooser.append(self._ipsw_label)
        page.append(chooser)
        self._match = label("", "caption", wrap=True)
        self._match.set_visible(False)
        page.append(self._match)

        page.append(label("WHAT TO DO", "section-title"))
        self._update = Gtk.CheckButton(label=f"Update: install this {self._os} and keep all data", active=True)
        self._erase = Gtk.CheckButton(label=f"Restore: erase everything and install a clean {self._os}",
                                      group=self._update)
        self._erase.connect("toggled", lambda *_: self._refresh())
        page.append(self._update)
        page.append(self._erase)

        self._warning = label("", "warning-box", wrap=True)
        page.append(self._warning)
        self._ack = Gtk.CheckButton()
        self._ack.connect("toggled", lambda *_: self._refresh())
        page.append(self._ack)
        page.append(label("Apple only lets devices install versions it still signs, so an older .ipsw may be "
                          "refused. If the device restarts into recovery mode and is not found, add "
                          "libirecovery's udev rules.", "caption", wrap=True))

        spacer = Gtk.Box(vexpand=True)
        page.append(spacer)
        self._start = button("Update", None, "primary", "big")
        self._start.set_halign(Gtk.Align.END)
        self._start.connect("clicked", self._on_start)
        page.append(self._start)
        self._refresh()
        return page

    def _progress_page(self):
        page = vbox(16)
        page.set_valign(Gtk.Align.CENTER)
        self._margins(page, 32)
        self._progress_title = label("", "h2")
        page.append(self._progress_title)
        card = vbox(14, "progress-card")
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
        card.append(self._detail)
        page.append(card)
        page.append(label("Keep the device plugged in. It restarts several times; do not unplug it until "
                          "this window says it is finished.", "caption", wrap=True))
        return page

    def _result_page(self):
        page = vbox(14)
        page.set_valign(Gtk.Align.CENTER)
        page.set_halign(Gtk.Align.CENTER)
        self._result_icon = Gtk.Image(pixel_size=56)
        self._result_title = label("", "h2", xalign=0.5)
        self._result_text = label("", "body-text", xalign=0.5, wrap=True)
        self._result_text.set_max_width_chars(52)
        self._result_text.set_justify(Gtk.Justification.CENTER)
        close = button("Close", None, "primary", "big")
        close.set_halign(Gtk.Align.CENTER)
        close.connect("clicked", lambda *_: self.close())
        for widget in (self._result_icon, self._result_title, self._result_text, close):
            page.append(widget)
        return page

    def _on_tool(self, state: str):
        self._tool = state
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
                self._ipsw = source.open_finish(result).get_path()
            except GLib.Error:
                return
            self._refresh()

        dialog.open(self, None, chosen)

    def _file_ok(self) -> bool:
        if not self._ipsw:
            self._ipsw_label.set_label("No file chosen")
            self._match.set_visible(False)
            return False
        path = Path(self._ipsw)
        size = path.stat().st_size if path.is_file() else 0
        self._ipsw_label.set_label(f"{path.name} · {format_size(size)}")
        match = ipsw_matches(path.name, self._device.product_type) if self._device.product_type else None
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
            self._warning.set_label(f"Restore erases everything on {name}. Back it up first. Afterwards the "
                                    "device asks for the Apple ID and password it was set up with.")
        else:
            self._warning.set_label(f"Back up {name} first. An interrupted update can leave the device in "
                                    "recovery mode, and a backup is the only way to get the data back.")
        self._ack.set_label(f"I understand everything on {name} will be erased" if erase
                            else f"I have a recent backup of {name}")
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
        elif isinstance(event, OverallPercent):
            self._stop_pulse()
            self._bar.set_fraction(event.value / 100)
            self._percent.set_label(f"{event.value:.0f}%")
        elif isinstance(event, Error):
            self._detail.set_label(event.message)

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
        self._window.notify_done(f"{self._os} update finished" if success else f"{self._os} update failed",
                                 self._device.name)
        self._stack.set_visible_child_name("result")
