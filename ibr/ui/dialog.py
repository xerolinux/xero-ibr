from gi.repository import Gdk, Gtk

from .widgets import button, hbox, label, vbox


class Dialog(Gtk.Window):
    def __init__(self, parent: Gtk.Window, title: str, width: int, height: int = -1):
        super().__init__(transient_for=parent, modal=True, title=title, resizable=False)
        self.add_css_class("ibr")
        self.set_default_size(width, height)
        header = Gtk.HeaderBar()
        header.set_title_widget(label(title, "h3"))
        self.set_titlebar(header)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)

    def _on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape and self.get_deletable():
            self.close()
            return True
        return False


class MessageDialog(Dialog):
    """App-styled replacement for Gtk.AlertDialog, which follows the system theme instead of ours."""

    ICONS = {"info": "dialog-information-symbolic", "warning": "dialog-warning-symbolic",
             "danger": "dialog-warning-symbolic"}

    def __init__(self, parent, heading: str, body: str, buttons: list[tuple[str, str]], callback=None,
                 kind: str = "info"):
        super().__init__(parent, "", 600)
        self._callback = callback
        self._answered = False
        content = vbox(16)
        for side, value in (("top", 20), ("bottom", 24), ("start", 28), ("end", 28)):
            getattr(content, f"set_margin_{side}")(value)
        top = hbox(14)
        icon = Gtk.Image.new_from_icon_name(self.ICONS.get(kind, self.ICONS["info"]))
        icon.set_pixel_size(40)
        icon.set_valign(Gtk.Align.START)
        icon.add_css_class(f"message-icon-{kind}")
        top.append(icon)
        text = vbox(8)
        text.set_hexpand(True)
        text.append(label(heading, "h3", wrap=True))
        message = label(body, "body-text", wrap=True)
        message.set_justify(Gtk.Justification.FILL)
        message.set_max_width_chars(70)
        message.set_width_chars(56)
        text.append(message)
        top.append(text)
        content.append(top)

        actions = hbox(10)
        actions.set_halign(Gtk.Align.END)
        actions.set_margin_top(6)
        default = None
        for index, (title, style) in enumerate(buttons):
            widget = button(title, None, style)
            widget.connect("clicked", lambda _b, i=index: self._answer(i))
            actions.append(widget)
            if style in ("primary", "danger-solid"):
                default = widget
        content.append(actions)
        self.set_child(content)
        if default:
            self.set_default_widget(default)
        self.connect("close-request", self._on_close)

    def _answer(self, index: int):
        self._answered = True
        if self._callback:
            self._callback(index)
        self.destroy()

    def _on_close(self, *_):
        if not self._answered and self._callback:
            self._answered = True
            self._callback(-1)
        return False


def confirm(parent: Gtk.Window, heading: str, body: str, accept: str, callback, destructive: bool = False):
    buttons = [("Cancel", "outline"), (accept, "danger-solid" if destructive else "primary")]
    MessageDialog(parent, heading, body, buttons, lambda index: callback(index == 1),
                  kind="danger" if destructive else "info").present()


def alert(parent: Gtk.Window, heading: str, body: str, kind: str = "info"):
    MessageDialog(parent, heading, body, [("OK", "primary")], kind=kind).present()
