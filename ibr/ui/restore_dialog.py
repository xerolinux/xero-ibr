from gi.repository import GLib, Gtk

from ..core.backups import BackupEntry
from ..core.compat import problem_detail, restore_problem
from ..core.commands import RestoreOptions, restore_cmd
from ..core.deviceinfo import DeviceInfo
from ..core.fmt import format_date
from ..services import keyring
from ..services.operation import Operation
from .dialog import Dialog, alert, confirm
from .progress_card import ProgressCard
from .widgets import button, hbox, label, set_classes, vbox


class RestoreDialog(Dialog):
    def __init__(self, window, device: DeviceInfo, entries: list[BackupEntry], preselect: BackupEntry | None):
        super().__init__(window, f"Restore {device.name}", 900, 580)
        self._window = window
        self._device = device
        self._settings = window.settings
        self._operation = None
        self._choice: BackupEntry | None = None

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.add_named(self._choose_page(entries, preselect), "choose")
        self._stack.add_named(self._progress_page(), "progress")
        self._stack.add_named(self._result_page(), "result")
        self.set_child(self._stack)
        self.connect("close-request", lambda *_: bool(self._operation and self._operation.running))

    def _choose_page(self, entries, preselect):
        page = hbox(22)
        for side in ("top", "bottom", "start", "end"):
            getattr(page, f"set_margin_{side}")(24)

        left = vbox(10)
        left.set_hexpand(True)
        left.set_size_request(470, -1)
        left.append(label("Choose a backup", "h3"))
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        options = vbox(10)
        scroller.set_child(options)
        left.append(scroller)
        page.append(left)

        group = None
        first_valid = None
        latest_seen = set()
        problems = {id(entry): restore_problem(entry, self._device) for entry in entries}
        entries = sorted(entries, key=lambda e: problems[id(e)] is not None)
        for entry in entries:
            problem = problems[id(entry)]
            radio = Gtk.CheckButton()
            if group:
                radio.set_group(group)
            group = group or radio
            box = hbox(14, "restore-option")
            box.append(radio)
            text = vbox(2)
            text.set_hexpand(True)
            when = format_date(entry.local_date) if entry.local_date else "Unknown date"
            text.append(label(f"{entry.device_name} · {when}", "h3", ellipsize=True))
            details = [entry.os_version or "Unknown version", self._window.size_of(entry) or "…",
                       "Encrypted" if entry.encrypted else "Not encrypted"]
            text.append(label(problem or " · ".join(details), "caption", ellipsize=True))
            box.append(text)
            if entry.udid not in latest_seen:
                latest_seen.add(entry.udid)
                box.append(label("Latest", "pill", "info"))
            if problem:
                radio.set_sensitive(False)
                box.add_css_class("disabled")
                why = button("", "dialog-information-symbolic", "flat", tooltip="Why can't this be restored?")
                why.connect("clicked", lambda _b, e=entry: self._explain(e))
                box.append(why)
            elif first_valid is None or entry is preselect:
                first_valid = radio
            radio.connect("toggled", self._on_pick, entry, box)
            click = Gtk.GestureClick()
            click.connect("released", lambda *_a, r=radio, e=entry: r.set_active(True) if r.get_sensitive()
                          else self._explain(e))
            box.add_controller(click)
            options.append(box)
        if not entries:
            options.append(label("No backups found in the backup folder.", "empty-box", xalign=0.5))

        right = vbox(14, "side-panel")
        right.set_size_request(300, -1)
        right.set_hexpand(False)
        warning = hbox(10, "warning-box")
        warning.append(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        kind = "iPad" if self._device.spec.kind == "ipad" else "iPhone"
        warning_text = label(f"Restoring replaces all data on this {kind}. Turn off Find My on the "
                             f"{kind} first (Settings > your name > Find My).", wrap=True)
        warning_text.set_max_width_chars(30)
        warning.append(warning_text)
        right.append(warning)

        self._password_box = vbox(6)
        self._password_box.append(label("Backup password", "card-label"))
        self._password = Gtk.PasswordEntry(show_peek_icon=True)
        self._password.update_property([Gtk.AccessibleProperty.LABEL], ["Backup password"])
        self._password_box.append(self._password)
        self._remember = Gtk.CheckButton(label="Remember in the system keyring",
                                         active=self._settings.remember_password)
        self._password_box.append(self._remember)
        right.append(self._password_box)

        self._system = Gtk.CheckButton(label="Include system files (advanced)", active=self._settings.restore_system)
        self._system.set_tooltip_text("Also restores data from the backup's system areas. Rarely needed; leave off "
                                      "when restoring to a different device.")
        self._restore_settings = Gtk.CheckButton(label="Restore device settings",
                                                 active=self._settings.restore_settings)
        self._reboot = Gtk.CheckButton(label="Restart the device when finished",
                                       active=self._settings.restore_reboot)
        for widget in (self._system, self._restore_settings, self._reboot):
            right.append(widget)

        spacer = Gtk.Box(vexpand=True)
        right.append(spacer)
        self._go = button("Restore Backup", None, "primary", "big")
        self._go.connect("clicked", self._on_restore)
        right.append(self._go)
        page.append(right)

        if first_valid:
            first_valid.set_active(True)
        else:
            self._go.set_sensitive(False)
            self._password_box.set_visible(False)
            own = [e for e in entries if e.udid == self._device.udid] or entries
            if own:
                GLib.idle_add(lambda: self._explain(own[0]) and False)
        return page

    def _explain(self, entry: BackupEntry):
        alert(self, "This backup can't be restored", problem_detail(entry, self._device), kind="warning")

    def _on_pick(self, radio, entry, box):
        set_classes(box, *(["selected"] if radio.get_active() else []), keep=("restore-option",))
        if not radio.get_active():
            return
        self._choice = entry
        self._password_box.set_visible(entry.encrypted)
        if entry.encrypted:
            self._password.set_text(keyring.lookup(entry.udid) or "")

    def _progress_page(self):
        page = vbox(18)
        page.set_valign(Gtk.Align.CENTER)
        for side in ("top", "bottom", "start", "end"):
            getattr(page, f"set_margin_{side}")(36)
        self._progress_title = label("", "h2")
        page.append(self._progress_title)
        self._card = ProgressCard()
        page.append(self._card)
        page.append(label("Keep the device connected and unlocked. Do not unplug it until it restarts.",
                          "caption", wrap=True))
        return page

    def _result_page(self):
        page = vbox(14)
        page.set_valign(Gtk.Align.CENTER)
        page.set_halign(Gtk.Align.CENTER)
        self._result_icon = Gtk.Image(pixel_size=56)
        page.append(self._result_icon)
        self._result_title = label("", "h2", xalign=0.5)
        self._result_text = label("", "body-text", xalign=0.5, wrap=True)
        self._result_text.set_max_width_chars(56)
        self._result_text.set_justify(Gtk.Justification.CENTER)
        page.append(self._result_title)
        page.append(self._result_text)
        close = button("Close", None, "primary", "big")
        close.set_halign(Gtk.Align.CENTER)
        close.connect("clicked", lambda *_: self.close())
        page.append(close)
        return page

    def _on_restore(self, *_):
        entry = self._choice
        if entry is None:
            return
        if entry.encrypted and not self._password.get_text():
            self._password.grab_focus()
            return
        confirm(self, f"Erase {self._device.name} and restore?",
                f"Everything on {self._device.name} is replaced with the backup from "
                f"{format_date(entry.local_date) if entry.local_date else 'an unknown date'}.",
                "Erase and Restore", self._confirmed, destructive=True)

    def _confirmed(self, accepted: bool):
        if not accepted:
            return
        entry = self._choice
        options = RestoreOptions(
            source_udid=entry.udid,
            password=self._password.get_text() if entry.encrypted else None,
            system=self._system.get_active(),
            settings=self._restore_settings.get_active(),
            reboot=self._reboot.get_active(),
            copy=self._settings.restore_copy,
            remove=self._settings.restore_remove,
            skip_apps=self._settings.restore_skip_apps,
        )
        argv, env = restore_cmd(self._device.udid, str(entry.restore_root), options)
        self._operation = Operation("restore", argv, env)
        self._operation.connect("event", lambda _op, event: self._card.handle(event))
        self._operation.connect("done", self._on_done)
        self._progress_title.set_label(f"Restoring {self._device.name}")
        self._card.reset("restore")
        self._stack.set_visible_child_name("progress")
        self.set_deletable(False)
        self._window.begin_operation("Restoring your device")
        self._operation.start()

    def _on_done(self, operation, success: bool, message: str):
        entry = self._choice
        self._window.end_operation()
        self.set_deletable(True)
        if success and entry.encrypted and self._remember.get_active():
            keyring.store(entry.udid, entry.device_name, self._password.get_text())
        self._result_icon.set_from_icon_name("object-select-symbolic" if success else "dialog-warning-symbolic")
        set_classes(self._result_icon, *([] if success else ["fail"]), keep=("result-icon",))
        if success:
            self._result_title.set_label("Restore complete")
            self._result_text.set_label(f"{self._device.name} restarts and finishes setting up on its own. "
                                        "Keep it connected to Wi-Fi so apps can download again.")
        else:
            self._result_title.set_label("Restore failed")
            self._result_text.set_label(message)
        self._window.notify_done("Restore complete" if success else "Restore failed",
                                 self._device.name if success else message)
        self._stack.set_visible_child_name("result")
