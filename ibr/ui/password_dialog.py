from gi.repository import Gtk

from .dialog import Dialog
from .widgets import button, hbox, label, vbox


class PasswordDialog(Dialog):
    """mode: "current" asks one password, "new" asks new + confirm, "change" asks all three."""

    def __init__(self, parent, title: str, message: str, mode: str, callback, remember: bool | None = None,
                 accept: str = "Continue"):
        super().__init__(parent, title, 440)
        self._mode = mode
        self._callback = callback
        self._answered = False

        body = vbox(14)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(22)
        body.append(label(message, "body-text", wrap=True))

        self._current = self._entry(body, "Current backup password") if mode in ("current", "change") else None
        self._new = self._entry(body, "New password") if mode in ("new", "change") else None
        self._confirm = self._entry(body, "Confirm new password") if mode in ("new", "change") else None

        self._ack = None
        if self._new is not None:
            warning = label("Write this password down. Without it, encrypted backups cannot be restored, "
                            "and nobody (including Apple) can recover it.", "warning-box", wrap=True)
            body.append(warning)
            self._ack = Gtk.CheckButton(label="I understand that losing this password means losing these backups")
            body.append(self._ack)

        self._remember = None
        if remember is not None:
            self._remember = Gtk.CheckButton(label="Remember in the system keyring", active=remember)
            body.append(self._remember)

        self._error = label("", "caption", wrap=True)
        self._error.add_css_class("device-status")
        self._error.add_css_class("warn")
        self._error.set_visible(False)
        body.append(self._error)

        actions = hbox(10)
        actions.set_halign(Gtk.Align.END)
        cancel = button("Cancel", None, "outline")
        cancel.connect("clicked", lambda *_: self.close())
        ok = button(accept, None, "primary")
        ok.connect("clicked", self._submit)
        if self._ack is not None:
            ok.set_sensitive(False)
            self._ack.connect("toggled", lambda check: ok.set_sensitive(check.get_active()))
        actions.append(cancel)
        actions.append(ok)
        body.append(actions)
        self.set_child(body)
        self.set_default_widget(ok)
        self.connect("close-request", self._on_close)
        first = self._current or self._new
        if first:
            first.grab_focus()

    def _entry(self, box: Gtk.Box, title: str) -> Gtk.PasswordEntry:
        column = vbox(6)
        column.append(label(title, "card-label"))
        entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [title])
        column.append(entry)
        box.append(column)
        return entry

    def _fail(self, text: str):
        self._error.set_label(text)
        self._error.set_visible(True)

    def _submit(self, *_):
        result = {"remember": self._remember.get_active() if self._remember else False}
        if self._current is not None:
            if not self._current.get_text():
                return self._fail("Enter the current backup password.")
            result["current"] = self._current.get_text()
        if self._new is not None:
            if len(self._new.get_text()) < 4:
                return self._fail("Use at least 4 characters.")
            if self._new.get_text() != self._confirm.get_text():
                return self._fail("The passwords do not match.")
            result["new"] = self._new.get_text()
        self._answered = True
        self._callback(result)
        self.destroy()

    def _on_close(self, *_):
        if not self._answered:
            self._answered = True
            self._callback(None)
        return False
