from importlib.resources import files

from gi.repository import Gtk

from .. import __version__
from ..constants import APP_NAME, APP_SHORT, DISCORD_URL, GITHUB_URL
from ..core.support import MIN_OS_LABEL
from .dialog import Dialog
from .widgets import button, hbox, label, vbox


def about_logo_path() -> str:
    data = files("ibr") / "data"
    custom = data / "about-logo.svg"
    return str(custom if custom.is_file() else data / "com.techxero.ibr.svg")


class AboutWindow(Dialog):
    def __init__(self, window):
        super().__init__(window, f"About {APP_SHORT}", 420)
        body = vbox(14)
        body.set_halign(Gtk.Align.CENTER)
        for side, value in (("top", 28), ("bottom", 22), ("start", 30), ("end", 30)):
            getattr(body, f"set_margin_{side}")(value)

        logo = Gtk.Image.new_from_file(about_logo_path())
        logo.set_pixel_size(104)
        logo.update_property([Gtk.AccessibleProperty.LABEL], [f"{APP_NAME} logo"])
        body.append(logo)
        body.append(label(APP_NAME, "about-name", xalign=0.5))
        body.append(label(f"{APP_SHORT} · Version {__version__}", "caption", xalign=0.5))
        text = label("Back up, restore and transfer files with iPhone and iPad on Linux. Built on libimobiledevice. "
                     f"Supports {MIN_OS_LABEL} and later.", "body-text", xalign=0.5, wrap=True)
        text.set_justify(Gtk.Justification.CENTER)
        text.set_max_width_chars(40)
        body.append(text)

        links = hbox(10)
        links.set_homogeneous(True)
        links.set_margin_top(6)
        for title, icon, url, css in (("GitHub", "text-x-script-symbolic", GITHUB_URL, "outline"),
                                      ("Discord", "user-available-symbolic", DISCORD_URL, "discord")):
            link = button(title, icon, "about-link", css)
            link.set_sensitive(bool(url))
            link.connect("clicked", lambda _b, target=url: Gtk.UriLauncher.new(target).launch(self, None, None))
            links.append(link)
        body.append(links)
        body.append(label("MIT License · Not affiliated with Apple Inc.", "caption", xalign=0.5))
        close = button("Close", None, "flat")
        close.set_halign(Gtk.Align.CENTER)
        close.connect("clicked", lambda *_: self.close())
        body.append(close)
        self.set_child(body)
