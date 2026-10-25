from gi.repository import Gdk, GLib, GObject, Gtk

from ..core.catalog import lookup
from ..core.recovery import UDEV_RULE, UDEV_RULE_PATH
from .device_art import DeviceArt
from .widgets import button, hbox, label, set_button_text, vbox

_EXPLAIN = {
    "Recovery": "It is waiting to be restored. Try Exit Recovery Mode first; if it comes back here, restore it "
                "with an .ipsw.",
    "DFU": "DFU mode is only used to install firmware. Restore it with an .ipsw, or hold the side and volume "
           "buttons until the Apple logo appears to leave DFU.",
    "WTF": "This is a low-level firmware mode. Restore it with an .ipsw.",
}
MANUAL_COMMAND = (f"echo '{UDEV_RULE.strip()}' | sudo tee {UDEV_RULE_PATH} && "
                  "sudo udevadm control --reload-rules && sudo udevadm trigger")


class RecoveryView(Gtk.Box):
    __gsignals__ = {
        "exit-recovery": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "restore": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "grant-access": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(spacing=48)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(28 if side in ("top", "bottom") else 44)
        self.set_valign(Gtk.Align.CENTER)
        self.art = DeviceArt(330, 450)
        self.append(self.art)
        column = vbox(14)
        column.set_hexpand(True)
        column.set_valign(Gtk.Align.CENTER)
        self._pill = label("", "pill", "warn")
        self._pill.set_halign(Gtk.Align.START)
        self._title = label("", "h2", wrap=True)
        self._model = label("", "subtitle", wrap=True)
        self._text = label("", "body-text", wrap=True)
        for widget in (self._pill, self._title, self._model, self._text):
            column.append(widget)

        self._access = vbox(10, "warning-box")
        self._access.append(label("iBR cannot talk to the device in this mode yet. Allow USB access once; it "
                                  "asks for your password and only covers Apple Recovery and DFU modes.", wrap=True))
        access_actions = hbox(10)
        grant = button("Allow USB Access…", "changes-allow-symbolic", "primary")
        grant.connect("clicked", lambda *_: self.emit("grant-access"))
        copy = button("Copy terminal command", "edit-copy-symbolic", "outline")
        copy.connect("clicked", lambda *_: self.get_clipboard().set_content(
            Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(MANUAL_COMMAND.encode()))))
        access_actions.append(grant)
        access_actions.append(copy)
        self._access.append(access_actions)
        column.append(self._access)

        actions = hbox(10)
        self._exit = button("Exit Recovery Mode", "system-reboot-symbolic", "outline", "big")
        self._exit.connect("clicked", lambda *_: self.emit("exit-recovery"))
        self._restore = button("Update or Restore iOS", "software-update-available-symbolic", "primary", "big")
        self._restore.connect("clicked", lambda *_: self.emit("restore"))
        actions.append(self._exit)
        actions.append(self._restore)
        column.append(actions)
        self._banner = label("", "banner", wrap=True)
        self._banner.set_visible(False)
        column.append(self._banner)
        self.append(column)

    def update(self, device, needs_access: bool):
        spec = lookup(device.product_type or "", "iPhone")
        self.art.set_device(spec, product_type=device.product_type)
        name = device.name or (spec.name if device.product_type else "Your device")
        os_name = "iPadOS" if (device.product_type or "").startswith("iPad") else "iOS"
        self._pill.set_label(f"{device.mode} mode")
        self._title.set_label(f"{name} is in {device.mode} mode")
        model = device.product_type or "unknown model"
        self._model.set_label(f"{model} · ECID {device.ecid}" if device.ecid else model)
        self._text.set_label(_EXPLAIN.get(device.mode, _EXPLAIN["WTF"]))
        self._access.set_visible(needs_access)
        self._exit.set_visible(device.mode == "Recovery")
        self._exit.set_sensitive(not needs_access)
        self._restore.set_sensitive(not needs_access)
        set_button_text(self._restore, f"Update or Restore {os_name}")

    def show_banner(self, kind: str, text: str):
        self._banner.set_label(text)
        self._banner.set_css_classes(["banner", kind])
        self._banner.set_visible(bool(text))
