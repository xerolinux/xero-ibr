import shlex
import shutil
from pathlib import Path

from gi.repository import Gio, GLib, Gtk

from .. import __version__
from ..constants import APP_ID, APP_NAME, LICENSE_NOTE, TAGLINE
from ..core.backups import BackupEntry, dir_size, scan_backups
from ..core.catalog import lookup
from ..core.commands import backup_cmd, changepw_cmd, encryption_cmd
from ..core.firmware import FirmwareTarget
from ..core.recovery import UDEV_RULE, UDEV_RULE_PATH, clean_transfers, usbmuxd_install_hint
from ..core.settings import xdg_dir
from ..core.fmt import format_size
from ..core.progress import Copied, Percent
from ..core.snapshots import create_snapshot, mark_damaged, new_stamp, prune_snapshots
from ..core.support import MIN_OS_LABEL, is_supported
from ..services import keyring
from ..services.devices import Device, DeviceMonitor
from ..services.operation import Operation
from ..services import updater
from ..services.homescreen import fetch_home
from ..services.runner import in_thread, missing_tools, run
from .about_window import AboutWindow
from .backups_window import BackupsWindow
from .device_view import DeviceView
from .dialog import alert, confirm
from .files_view import FilesView
from .firmware_dialog import FirmwareDialog
from .recovery_view import RecoveryView
from .password_dialog import PasswordDialog
from .restore_dialog import RestoreDialog
from .scanning_view import ScanningView
from .settings_window import SettingsWindow
from .sidebar import Sidebar, SidebarDevice
from .widgets import button, hbox, label, set_button_text, vbox

TIPS = (
    "Use a cable that carries data, not only charging.",
    "Unlock the device and tap Trust when it asks.",
    "Check the service with: systemctl status usbmuxd",
    "Logs are in Settings > Advanced > Log folder.",
)


RECOVERY_PREFIX = "recovery:"


def _os_release() -> str:
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            return Path(path).read_text()
        except OSError:
            continue
    return ""


def _without_icon(layout: str | None) -> str:
    def clean(side: str) -> str:
        return ",".join(part for part in side.split(",") if part and part != "icon")

    left, _, right = (layout or ":minimize,maximize,close").partition(":")
    return f"{clean(left)}:{clean(right)}"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, settings, monitor: DeviceMonitor | None = None):
        super().__init__(application=app, title=APP_NAME)
        self.add_css_class("ibr")
        self.set_default_size(1120, 720)
        self.set_size_request(900, 620)
        self.settings = settings
        self.monitor = monitor or DeviceMonitor()
        self.backups: list[BackupEntry] = []
        self.current: str | None = None
        self.operation: Operation | None = None
        self._sizes: dict[Path, int] = {}
        self._sizing: set[Path] = set()
        self._busy_udid: str | None = None
        self._busy_percent: float | None = None
        self._inhibit = 0
        self._auto_done: set[str] = set()
        self._op_active = False
        self._quit_after = False
        self._copied: list[str] = []
        self._homes: dict = {}
        self._missing = missing_tools()

        self._build_header()
        root = vbox(0)
        body = hbox(0)
        body.set_vexpand(True)
        self.sidebar = Sidebar(self.size_of)
        self.sidebar.set_location(self.settings.backup_dir)
        self.sidebar.connect("device-selected", self._on_device_selected)
        self.sidebar.connect("backup-activated", self._on_backup_activated)
        self._sidebar_revealer = Gtk.Revealer(child=self.sidebar, reveal_child=True, transition_duration=150,
                                              transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
                                              hexpand=False)
        body.append(self._sidebar_revealer)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
        self.scanning = ScanningView()
        self._stack.add_named(self.scanning, "scan")
        self.device_view = DeviceView()
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.device_view)
        self._stack.add_named(scroller, "device")
        self.device_view.connect("backup", lambda *_: self.start_backup(self.current))
        self.device_view.connect("restore", lambda *_: self.open_restore())
        self.device_view.connect("manage", lambda *_: BackupsWindow(self, self.current).present())
        self.device_view.connect("cancel", lambda *_: self.operation and self.operation.cancel())
        self.device_view.connect("encrypt-toggled", self._on_encrypt_toggled)
        self.device_view.connect("files", lambda *_: self.open_files())
        self.device_view.connect("software", lambda *_: self.open_software())
        self.recovery_view = RecoveryView()
        self.recovery_view.connect("exit-recovery", lambda *_: self._exit_recovery())
        self.recovery_view.connect("restore", lambda *_: self._restore_recovery())
        self.recovery_view.connect("grant-access", lambda *_: self._grant_usb_access())
        recovery_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        recovery_scroller.set_child(self.recovery_view)
        self._stack.add_named(recovery_scroller, "recovery")
        self.files_view = FilesView(self)
        self.files_view.connect("close", lambda *_: self.close_files())
        self._stack.add_named(self.files_view, "files")
        self._files_open = False
        body.append(self._stack)
        root.append(body)
        root.append(self._build_footer())
        self.set_child(root)

        self.monitor.connect("changed", lambda *_: self._on_devices_changed())
        self.monitor.connect("scanning", self._on_scanning)
        self.connect("close-request", self._on_close_request)

        self.refresh_ui()
        self.reload_backups()
        if not self._missing:
            self.monitor.scan()
            self.monitor.set_polling(self.settings.auto_detect)
        self._update_info = None
        in_thread(lambda: clean_transfers(xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "transfers"), lambda _: None)
        GLib.timeout_add_seconds(5, self._check_update)
        GLib.timeout_add_seconds(6 * 3600, self._check_update)

    def _build_header(self):
        header = Gtk.HeaderBar()
        brand = hbox(8)
        logo = Gtk.Image.new_from_icon_name(APP_ID)
        logo.set_pixel_size(22)
        brand.append(logo)
        title = label(APP_NAME, "app-title")
        title.set_valign(Gtk.Align.CENTER)
        title.set_tooltip_text(TAGLINE)
        brand.append(title)
        header.pack_start(brand)
        self._sidebar_toggle = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", active=True)
        self._sidebar_toggle.add_css_class("icon")
        self._sidebar_toggle.set_tooltip_text("Show or hide the device list")
        self._sidebar_toggle.update_property([Gtk.AccessibleProperty.LABEL], ["Show or hide the device list"])
        self._sidebar_toggle.connect("toggled", lambda b: self._sidebar_revealer.set_reveal_child(b.get_active()))
        header.pack_start(self._sidebar_toggle)
        header.set_title_widget(Gtk.Box())
        header.set_decoration_layout(_without_icon(Gtk.Settings.get_default().props.gtk_decoration_layout))

        about = button("", "help-about-symbolic", tooltip="About iBR")
        about.connect("clicked", lambda *_: AboutWindow(self).present())
        settings = button("", "emblem-system-symbolic", tooltip="Settings")
        settings.connect("clicked", lambda *_: self.open_settings())
        self._scan = button("Scan for Devices", "view-refresh-symbolic", "primary")
        self._scan.connect("clicked", lambda *_: self.monitor.scan(refresh=True))
        self._update = button("Update", "software-update-available-symbolic", "update")
        self._update.set_visible(False)
        self._update.connect("clicked", lambda *_: self._install_update())
        for widget in (about, settings, self._scan, self._update):
            header.pack_end(widget)
        self.set_titlebar(header)

    def _build_footer(self) -> Gtk.Widget:
        footer = Gtk.CenterBox()
        footer.add_css_class("footer")
        status = hbox(6)
        status.set_valign(Gtk.Align.CENTER)
        self._dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self._dot.add_css_class("status-dot")
        self._status = label("")
        status.append(self._dot)
        status.append(self._status)
        footer.set_start_widget(status)
        pill = label(LICENSE_NOTE, "license-pill", xalign=0.5, ellipsize=True)
        pill.set_valign(Gtk.Align.CENTER)
        pill.set_tooltip_text(LICENSE_NOTE)
        footer.set_center_widget(pill)

        tips = vbox(8)
        tips.append(label("Troubleshooting", "h3"))
        for tip in TIPS:
            tips.append(label(f"•  {tip}", "body-text", wrap=True))
        tips.append(label(f"Requires {MIN_OS_LABEL} or later.", "caption"))
        popover = Gtk.Popover(child=tips)
        popover.set_size_request(320, -1)
        help_button = Gtk.MenuButton(label="Troubleshoot", popover=popover, valign=Gtk.Align.CENTER)
        help_button.add_css_class("link")
        footer.set_end_widget(help_button)
        return footer

    def current_device(self) -> Device | None:
        return self.monitor.devices.get(self.current) if self.current else None

    def current_device_info(self):
        device = self.current_device()
        return device.info if device and device.state == "ready" else None

    def size_of(self, entry: BackupEntry) -> str | None:
        if entry.path in self._sizes:
            return format_size(self._sizes[entry.path])
        if entry.path not in self._sizing:
            self._sizing.add(entry.path)

            def done(size, path=entry.path):
                self._sizing.discard(path)
                self._sizes[path] = size
                self.refresh_ui()

            in_thread(lambda path=entry.path: dir_size(path), done)
        return None

    def home_of(self, udid: str):
        if udid in self._homes:
            return self._homes[udid]
        self._homes[udid] = None

        def fetched(home):
            if udid in self.monitor.devices:
                self._homes[udid] = home
                self.refresh_ui()

        in_thread(lambda: fetch_home(udid), fetched)
        return None

    def reload_backups(self, then=None):
        root = Path(self.settings.backup_dir)

        def loaded(entries):
            self.backups = entries
            self.refresh_ui()
            if then:
                then()

        in_thread(lambda: scan_backups(root), loaded)

    def known_devices(self) -> dict[str, str]:
        names = {entry.udid: entry.device_name for entry in reversed(self.backups)}
        for udid, device in self.monitor.devices.items():
            if device.info:
                names[udid] = device.info.name
        return names

    def backups_for(self, udid: str) -> list[BackupEntry]:
        return [entry for entry in self.backups if entry.udid == udid]

    def current_recovery(self):
        if self.current and self.current.startswith(RECOVERY_PREFIX):
            return self.monitor.recovery.get(self.current[len(RECOVERY_PREFIX):])
        return None

    def _on_devices_changed(self):
        connected = self.monitor.devices
        if self.current not in connected and self.current_recovery() is None:
            ready = [u for u, d in connected.items() if d.state == "ready"]
            recovery = [RECOVERY_PREFIX + key for key in self.monitor.recovery]
            self.current = (ready or recovery or list(connected) or [None])[0]
        for udid in list(self._auto_done):
            if udid not in connected:
                self._auto_done.discard(udid)
        for udid in list(self._homes):
            if udid not in connected:
                del self._homes[udid]
        if self.settings.auto_backup and not self._op_active:
            for udid, device in connected.items():
                if device.state == "ready" and udid not in self._auto_done and is_supported(device.info.os_version):
                    self._auto_done.add(udid)
                    self.current = udid
                    self.start_backup(udid)
                    break
        self.refresh_ui()

    def _on_scanning(self, monitor, scanning: bool):
        set_button_text(self._scan, "Scanning…" if scanning else "Scan for Devices")
        self._scan.set_sensitive(not scanning and not self._op_active)

    def _on_device_selected(self, sidebar, udid: str):
        if udid in self.monitor.devices or (udid.startswith(RECOVERY_PREFIX)
                                            and udid[len(RECOVERY_PREFIX):] in self.monitor.recovery):
            self.current = udid
            self.refresh_ui()
        else:
            BackupsWindow(self, udid).present()

    def _on_backup_activated(self, sidebar, entry: BackupEntry):
        if not self.open_restore(entry):
            BackupsWindow(self, entry.udid).present()

    def _sidebar_devices(self) -> list[SidebarDevice]:
        items = []
        for key, device in self.monitor.recovery.items():
            spec = lookup(device.product_type or "", "iPhone")
            name = device.name or (spec.name if device.product_type else "Apple device")
            items.append(SidebarDevice(RECOVERY_PREFIX + key, name, spec, spec.finish, f"{device.mode} mode", "warn",
                                       None, self.backups_for(key)))
        for udid, device in self.monitor.devices.items():
            history = self.backups_for(udid)
            info = device.info
            if info:
                spec, finish, name = info.spec, info.finish, info.name or info.spec.name
            else:
                spec = lookup(history[0].product_type) if history else lookup("", "iPhone")
                finish, name = spec.finish, history[0].device_name if history else "New device"
            progress = None
            if udid == self._busy_udid:
                pct = self._busy_percent
                status, css = (f"Working · {pct:.0f}%" if pct is not None else "Working…"), "busy"
                progress = (pct or 0) / 100
            elif device.state == "trust":
                status, css = "Waiting for Trust", "warn"
            elif device.state == "checking":
                status, css = "Connecting…", ""
            elif device.state == "error":
                status, css = "Needs attention", "warn"
            elif not is_supported(info.os_version):
                status, css = f"Needs {MIN_OS_LABEL}+", "warn"
            else:
                status, css = "Connected via USB", "ok"
            items.append(SidebarDevice(udid, name, spec, finish, status, css, progress, history))
        known = set(self.monitor.devices)
        for entry in self.backups:
            if entry.udid in known:
                continue
            known.add(entry.udid)
            spec = lookup(entry.product_type)
            items.append(SidebarDevice(entry.udid, entry.device_name, spec, spec.finish, "Not connected",
                                       "", None, self.backups_for(entry.udid)))
        return items

    def refresh_ui(self):
        self.sidebar.update(self._sidebar_devices(), self.current)
        ok = self.monitor.usbmuxd_ok
        self._dot.set_css_classes(["status-dot", "ok"] if ok else ["status-dot"])
        state = {True: "usbmuxd connected", False: "usbmuxd idle", None: "Checking"}[ok]
        self._status.set_label(f"v{__version__} · {state}")
        self._status.set_tooltip_text("usbmuxd starts automatically when a device is plugged in." if ok is False
                                      else None)

        if self._missing:
            self.scanning.show("Required tools are missing",
                               "Install libimobiledevice and usbmuxd, then restart iBR.",
                               [(tool, "fail") for tool in self._missing], animating=False)
            self._stack.set_visible_child_name("scan")
            return
        recovery = self.current_recovery()
        if recovery is not None:
            missing = "No such file" in recovery.error
            self.recovery_view.update(recovery, bool(recovery.error) and not missing)
            if missing:
                self.recovery_view.show_banner("error", "irecovery is not installed. On Arch install libirecovery-git "
                                               "from the AUR; the AppImage already includes it.")
            self._stack.set_visible_child_name("recovery")
            return
        device = self.current_device()
        if device is None:
            has_daemon = bool(shutil.which("usbmuxd")) or ok
            daemon = ("usbmuxd installed", "done") if has_daemon else ("usbmuxd missing", "fail")
            subtitle = f"Connect it with a cable. Nothing leaves this computer. Requires {MIN_OS_LABEL} or later."
            if not has_daemon:
                subtitle = ("The usbmuxd system service is needed to talk to iPhone and iPad. Install it with: "
                            f"{usbmuxd_install_hint(_os_release())}")
            self.scanning.show("Looking for your iPhone or iPad", subtitle,
                               [daemon, ("Plug in with USB", "todo"), ("Unlock and tap Trust", "todo")])
            self._stack.set_visible_child_name("scan")
            return
        if device.state in ("checking", "trust", "error"):
            title = {"checking": "Connecting to your device", "trust": "Trust this computer",
                     "error": "Could not read the device"}[device.state]
            self.scanning.show(title, device.message or "Keep the device unlocked.",
                               [("libimobiledevice ready", "done"), ("Plugged in", "done"),
                                ("Unlock and tap Trust", "fail" if device.state == "error" else "todo")])
            self._stack.set_visible_child_name("scan")
            return
        history = self.backups_for(device.udid)
        latest = history[0] if history else None
        self.device_view.update(device.info, latest, self.size_of(latest) if latest else None,
                                self.settings.show_identifiers, bool(self.backups), self.home_of(device.udid))
        if not self._op_active:
            self.device_view.set_idle()
        self._stack.set_visible_child_name("files" if self._files_open else "device")

    @property
    def operation_active(self) -> bool:
        return self._op_active

    def begin_operation(self, reason: str):
        self._op_active = True
        self.monitor.paused = True
        self._scan.set_sensitive(False)
        if self.settings.keep_awake:
            self._inhibit = self.get_application().inhibit(self, Gtk.ApplicationInhibitFlags.SUSPEND, reason)

    def end_operation(self):
        self._op_active = False
        self.monitor.paused = False
        self._scan.set_sensitive(True)
        if self._inhibit:
            self.get_application().uninhibit(self._inhibit)
            self._inhibit = 0
        self.monitor.scan(refresh=True, quiet=True)

    def notify_done(self, title: str, body: str):
        if not self.settings.notify:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self.get_application().send_notification("ibr-operation", notification)

    def start_backup(self, udid: str | None):
        device = self.monitor.devices.get(udid) if udid else None
        if not device or not device.info or self._op_active:
            return
        root = Path(self.settings.backup_dir)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.device_view.show_banner("error", f"Cannot use the backup folder: {error.strerror}")
            return
        info = device.info
        if self.settings.warn_low_space and info.used_bytes:
            has_previous = (root / udid).is_dir()
            needed = info.used_bytes // 10 if has_previous else info.used_bytes
            free = shutil.disk_usage(root).free
            if free < needed:
                confirm(self, "Free space may not be enough",
                        f"The backup folder has {format_size(free)} free and this backup may need up to "
                        f"{format_size(needed)}.", "Back Up Anyway",
                        lambda ok: ok and self._run_backup(udid, root))
                return
        self._run_backup(udid, root)

    def _run_backup(self, udid: str, root: Path):
        device = self.monitor.devices.get(udid)
        if not device or not device.info or self._op_active:
            return
        info = device.info
        self._copied = []
        argv, env = backup_cmd(udid, str(root), full=self.settings.always_full)
        self.operation = Operation("backup", argv, env)
        self.operation.connect("event", self._on_backup_event)
        self.operation.connect("done", self._on_backup_done, udid, root, info.name)
        self._busy_udid = udid
        self._busy_percent = None
        self.begin_operation(f"Backing up {info.name}")
        self.device_view.set_busy("backup")
        self.refresh_ui()
        self.operation.start()

    def _on_backup_event(self, operation, event):
        if self.current == self._busy_udid:
            self.device_view.progress.handle(event)
        if isinstance(event, Percent):
            self._busy_percent = event.value
            self.sidebar.update(self._sidebar_devices(), self.current)
        elif isinstance(event, Copied):
            self._copied.append(event.path)

    def _on_backup_done(self, operation, success: bool, message: str, udid: str, root: Path, name: str):
        self.operation = None
        self._busy_udid = None
        self.device_view.progress.finish(success)
        if self._quit_after:
            self.end_operation()
            self.destroy()
            return
        if not success:
            self.end_operation()
            cancelled = message == "Cancelled"
            self.device_view.show_banner("info" if cancelled else "error",
                                         "Backup cancelled." if cancelled else f"Backup failed: {message}")
            if not cancelled:
                self.notify_done("Backup failed", f"{name}: {message}")
            self.refresh_ui()
            return

        keep = self.settings.keep_history
        copied = list(self._copied)

        def snapshot():
            mark_damaged(root, udid, copied)
            try:
                create_snapshot(root, udid, new_stamp(root, udid))
            except OSError:
                return False
            prune_snapshots(root, udid, keep)
            return True

        def snapshotted(ok: bool):
            self.end_operation()
            self._sizes.clear()
            note = "" if ok else " Backup history is off: this drive does not support links or reflinks."
            self.device_view.show_banner("success", f"Backup of {name} finished.{note}")
            self.notify_done("Backup complete", f"{name} is backed up.")
            self.reload_backups()

        in_thread(snapshot, snapshotted)

    def open_restore(self, preselect: BackupEntry | None = None) -> bool:
        info = self.current_device_info()
        if not info or self._op_active or not is_supported(info.os_version):
            return False
        RestoreDialog(self, info, self.backups, preselect).present()
        return True

    def _check_update(self):
        def found(info):
            self._update_info = info
            if info:
                self._update.set_tooltip_text(f"Version {info.version} is available. Click to update and restart.")
            self._update.set_visible(info is not None)

        updater.check(found)
        return GLib.SOURCE_CONTINUE

    def _install_update(self):
        info = self._update_info
        if not info:
            return
        if self._op_active:
            alert(self, "Finish the current task first", "iBR can update once the backup, restore or transfer "
                  "in progress has finished.")
            return
        self._update.set_sensitive(False)
        set_button_text(self._update, "Updating…")

        def progress(fraction):
            set_button_text(self._update, f"Updating {fraction * 100:.0f}%")

        def done(error):
            if error:
                self._update.set_sensitive(True)
                set_button_text(self._update, "Update")
                alert(self, "Update failed", f"iBR could not update to {info.version}: {error}", kind="warning")
                return
            updater.relaunch_after_exit()
            self.get_application().quit()

        updater.install(info, progress, done)

    def _exit_recovery(self):
        device = self.current_recovery()
        if not device:
            return

        def done(ok, message):
            self.recovery_view.show_banner("info" if ok else "error",
                                           "Restarting the device normally. It reappears here when it is ready."
                                           if ok else f"Could not leave {device.mode} mode: {message}")

        self.monitor.exit_recovery(device, done)

    def _restore_recovery(self):
        device = self.current_recovery()
        if device and not self._op_active:
            FirmwareDialog(self, FirmwareTarget.from_recovery(device.mode, device.product_type, device.name,
                                                              device.ecid)).present()

    def _grant_usb_access(self):
        if not shutil.which("pkexec"):
            self.recovery_view.show_banner("error", "pkexec is not available. Run the command shown above in a "
                                           "terminal instead.")
            return
        script = (f"printf '%s' {shlex.quote(UDEV_RULE)} > {UDEV_RULE_PATH} && udevadm control --reload-rules && "
                  "udevadm trigger --subsystem-match=usb --attr-match=idVendor=05ac")

        def done(status, out, err):
            if status != 0:
                self.recovery_view.show_banner("error", "USB access was not changed.")
                return
            for device in self.monitor.recovery.values():
                device.queried = False
            self.recovery_view.show_banner("success", "USB access allowed. Checking the device again…")
            GLib.timeout_add_seconds(2, lambda: self.monitor.scan(refresh=True, quiet=True) and False)

        run(["pkexec", "/bin/sh", "-c", script], done)

    def open_software(self):
        info = self.current_device_info()
        if info and not self._op_active:
            FirmwareDialog(self, FirmwareTarget.from_device(info)).present()

    def open_files(self):
        info = self.current_device_info()
        if not info or self._op_active:
            return
        self._files_open = True
        self._sidebar_toggle.set_active(False)
        self.files_view.show_device(info.udid, info.name)
        self.refresh_ui()

    def close_files(self):
        self._files_open = False
        self._sidebar_toggle.set_active(True)
        self.refresh_ui()

    def open_settings(self):
        SettingsWindow(self).present()

    def on_setting_changed(self, attr: str):
        if attr == "auto_detect":
            self.monitor.set_polling(self.settings.auto_detect)
        elif attr == "theme":
            self.get_application().apply_theme(self.settings.theme)
        elif attr == "backup_dir":
            self._sizes.clear()
            self.sidebar.set_location(self.settings.backup_dir)
            self.reload_backups()
        self.refresh_ui()

    def _run_simple(self, kind: str, argv, env, on_done):
        self.device_view.set_sensitive(False)
        self.begin_operation(kind)
        operation = Operation(kind, argv, env)

        def done(_op, success, message):
            self.device_view.set_sensitive(True)
            self.end_operation()
            on_done(success, message)

        operation.connect("done", done)
        operation.start()

    def _on_encrypt_toggled(self, view, enable: bool):
        info = self.current_device_info()
        if not info:
            return
        if enable:
            mode, title = "new", "Turn on encryption"
            text = ("Choose a password for encrypted backups. You need it to restore. "
                    "If you forget it, the backups cannot be used.")
        else:
            mode, title = "current", "Turn off encryption"
            text = "Enter the current backup password to turn encryption off."

        def answered(result):
            if result is None:
                view.set_encrypt(not enable)
                return
            password = result.get("new") or result.get("current")
            argv, env = encryption_cmd(info.udid, enable, password)
            view.show_banner("info", "Confirm on your device: enter its passcode when asked.")

            def finished(success, message):
                if success and enable and result["remember"]:
                    keyring.store(info.udid, info.name, password)
                if success and not enable:
                    keyring.clear(info.udid)
                if success:
                    view.show_banner("success", f"Encryption is now {'on' if enable else 'off'} for {info.name}.")
                else:
                    view.set_encrypt(not enable)
                    view.show_banner("error", f"Could not change encryption: {message}")

            self._run_simple("encryption", argv, env, finished)

        PasswordDialog(self, title, text, mode, answered,
                       remember=self.settings.remember_password if enable else None).present()

    def change_password(self):
        info = self.current_device_info()
        if not info:
            return

        def answered(result):
            if result is None:
                return
            argv, env = changepw_cmd(info.udid, result["current"], result["new"])
            self.device_view.show_banner("info", "Confirm on your device: enter its passcode when asked.")

            def finished(success, message):
                if success and result["remember"]:
                    keyring.store(info.udid, info.name, result["new"])
                self.device_view.show_banner("success" if success else "error",
                                             "Backup password changed." if success
                                             else f"Could not change the password: {message}")

            self._run_simple("changepw", argv, env, finished)

        PasswordDialog(self, "Change backup password", f"Change the backup password for {info.name}.",
                       "change", answered, remember=self.settings.remember_password).present()

    def unpair_current(self):
        device = self.current_device()
        if not device:
            return

        def answered(ok):
            if ok:
                run(["idevicepair", "-u", device.udid, "unpair"], lambda *_: self.monitor.scan(refresh=True))

        confirm(self, "Forget this computer?", "The device asks you to Trust this computer again the next "
                "time it connects.", "Forget", answered, destructive=True)

    def _on_close_request(self, *_):
        if not self._op_active:
            return False
        if self.operation and self.operation.kind == "backup":
            def answered(ok):
                if ok and self.operation:
                    self._quit_after = True
                    self.operation.cancel()
            confirm(self, "Stop the backup and quit?", "The backup in progress is cancelled.", "Stop and Quit",
                    answered, destructive=True)
        else:
            alert(self, "Please wait", "A restore or encryption change is in progress. Closing now could "
                  "leave the device in a bad state.", kind="warning")
        return True
