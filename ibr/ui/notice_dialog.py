from gi.repository import Gtk

from ..constants import APP_NAME, LICENSE_NOTE
from .dialog import Dialog
from .widgets import button, hbox, label, vbox

_SECTIONS = (
    ("1. AI-ASSISTED SOFTWARE", False,
     f"{APP_NAME} (\"iBR\") was developed with substantial help from AI coding tools. Its code is reviewed and "
     "tested by a human maintainer, but it may still contain errors, incomplete logic or unexpected behaviour."),
    ("2. WORK IN PROGRESS", False,
     f"iBR is under active development. Features may change, stop working or be removed without notice. "
     f"{LICENSE_NOTE}"),
    ("3. NO WARRANTY", True,
     "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT "
     "LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT."),
    ("4. USE AT YOUR OWN RISK", True,
     "Backing up, restoring, updating or erasing a device can cause data loss. You are responsible for keeping "
     "separate copies of your data. In no event shall the authors or copyright holders be liable for any claim, "
     "damages or other liability arising from the use of iBR."),
)


class NoticeDialog(Dialog):
    """One-time terms shown on first launch; declining quits the app."""

    def __init__(self, window):
        super().__init__(window, "Terms of Use", 600, 640)
        self._window = window
        self._agreed = False
        content = vbox(16)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(24)

        top = hbox(14)
        icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
        icon.set_pixel_size(24)
        icon.add_css_class("notice-icon")
        top.append(icon)
        heading = vbox(2)
        heading.set_valign(Gtk.Align.CENTER)
        heading.append(label("Please read before using iBR", "h3"))
        self._sub = label("Scroll to the end to continue", "caption")
        heading.append(self._sub)
        top.append(heading)
        content.append(top)

        terms = vbox(14, "terms-box")
        for title, warn, text in _SECTIONS:
            terms.append(label(title, "terms-heading", *(("warn",) if warn else ())))
            body = label(text, "terms-legal" if warn else "terms-text", wrap=True)
            body.set_max_width_chars(60)
            terms.append(body)
        terms.append(label("MIT License · Copyright DarkXero / XeroLinux", "caption"))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.add_css_class("terms-scroller")
        scroller.set_child(terms)
        content.append(scroller)

        actions = hbox(10)
        self._hint = label("Read to the end to enable I Agree", "caption")
        self._hint.set_hexpand(True)
        actions.append(self._hint)
        decline = button("Decline", None, "outline")
        decline.connect("clicked", lambda *_: self.close())
        actions.append(decline)
        self._agree = button("I Agree", None, "primary")
        self._agree.set_sensitive(False)
        self._agree.connect("clicked", self._on_agree)
        actions.append(self._agree)
        content.append(actions)
        self.set_child(content)

        adjustment = scroller.get_vadjustment()
        adjustment.connect("value-changed", self._check_read)
        adjustment.connect("changed", self._check_read)
        self.connect("close-request", self._on_close)

    def _check_read(self, adjustment: Gtk.Adjustment):
        if self._agree.get_sensitive() or adjustment.get_upper() <= 0:
            return
        if adjustment.get_upper() <= adjustment.get_page_size() + 1:
            self._sub.set_label("Read the terms below before you continue")
            self._hint.set_label("")
        elif adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 4:
            self._hint.set_label("Thanks for reading")
            self._hint.add_css_class("ok")
        else:
            return
        self._agree.set_sensitive(True)
        self.set_default_widget(self._agree)

    def _on_agree(self, *_):
        self._agreed = True
        settings = self._window.settings
        settings.notice_accepted = True
        settings.save()
        self.destroy()

    def _on_close(self, *_):
        if not self._agreed:
            self._window.get_application().quit()
        return False
