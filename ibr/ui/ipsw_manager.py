from gi.repository import Gtk

from .dialog import Dialog
from .firmware_dialog import FIRMWARE_PANEL
from .ipsw_panels import IpswDownloader, IpswLibrary
from .widgets import hbox, label, vbox


class IpswManager(Dialog):
    """Download and manage iPSW files without a device connected."""

    def __init__(self, window):
        super().__init__(window, "iPSW Manager", *FIRMWARE_PANEL)
        self.set_modal(False)
        body = vbox(16, "ipsw-manager")
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(20)
        hero = vbox(4)
        hero.set_halign(Gtk.Align.CENTER)
        logo = Gtk.Image(icon_name="ibr-ipsw", pixel_size=96, css_classes=["hero-logo"])
        hero.append(logo)
        hero.append(label("iPSW Manager", "h2", xalign=0.5))
        hero.append(label("Download signed firmware from Apple and keep your iPSW files in one place",
                          "subtitle", xalign=0.5))
        body.append(hero)
        columns = hbox(20)
        columns.set_homogeneous(True)
        columns.set_vexpand(True)
        self._library = IpswLibrary(window, manage=True)
        columns.append(self._library)
        self._downloader = IpswDownloader(
            window, None, idle_text="Downloads are checked against Apple's checksum and land in the library, "
                                    "where Update or Restore iOS picks them up. Apple only installs builds it "
                                    "still signs. The library follows Settings › iPSW folder.")
        self._downloader.connect("downloaded", lambda _d, path: (self._library.rescan(), window.ipsw_downloaded(path)))
        self._downloader.connect("in-library", lambda _d, path: self._library.select(path))
        columns.append(self._downloader)
        body.append(columns)
        self.set_child(body)
        self.connect("close-request", self._on_close)

    def _on_close(self, *_):
        self._downloader.stop()
        self._library.stop()
        return False
