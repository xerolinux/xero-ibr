from gi.repository import Gdk, GLib, Gtk

from .dialog import Dialog
from .widgets import button, hbox, label, vbox


class RevealDialog(Dialog):
    def __init__(self, parent, device_name: str, password: str):
        super().__init__(parent, "Saved backup password", 420)
        body = vbox(14)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(22)
        body.append(label(f"Backup password for {device_name}", "card-label"))
        secret = label(password, "h3", selectable=True, wrap=True)
        secret.add_css_class("mono")
        body.append(secret)
        body.append(label("Keep it somewhere safe. You need it to restore encrypted backups.", "caption", wrap=True))
        actions = hbox(10)
        actions.set_halign(Gtk.Align.END)
        copy = button("Copy", "edit-copy-symbolic", "outline")
        copy.connect("clicked", lambda *_: self.get_clipboard().set_content(
            Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(password.encode()))))
        close = button("Close", None, "primary")
        close.connect("clicked", lambda *_: self.close())
        actions.append(copy)
        actions.append(close)
        body.append(actions)
        self.set_child(body)
