import sys
from importlib.resources import files

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .constants import APP_ID, APP_NAME  # noqa: E402
from .core.settings import Settings  # noqa: E402
from .ui import sounds  # noqa: E402
from .ui.notice_dialog import NoticeDialog  # noqa: E402
from .ui.window import MainWindow  # noqa: E402

_SCHEMES = {
    "light": Gtk.InterfaceColorScheme.LIGHT,
    "dark": Gtk.InterfaceColorScheme.DARK,
}


class Application(Gtk.Application):
    def __init__(self, monitor=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self._monitor = monitor
        self.settings = None
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.settings = Settings.load()
        sounds.gate.enabled = self.settings.ui_sounds
        self._css = Gtk.CssProvider()
        self._css.load_from_path(str(files("ibr") / "data" / "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Settings.get_default().connect("notify::gtk-interface-color-scheme", lambda *_: self._sync_scheme())
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(str(files("ibr") / "data" / "icons"))
        self.apply_theme(self.settings.theme)

        for name, accels, handler in (
            ("scan", ["<Control>r", "F5"], lambda *_: self.window.monitor.scan(refresh=True)),
            ("settings", ["<Control>comma"], lambda *_: self.window.open_settings()),
            ("quit", ["<Control>q"], lambda *_: self.window.close()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self):
        first = not self.window
        if first:
            self.window = MainWindow(self, self.settings, self._monitor)
        self.window.present()
        if first and not self.settings.notice_accepted:
            NoticeDialog(self.window).present()

    def apply_theme(self, theme: str):
        settings = Gtk.Settings.get_default()
        if theme in _SCHEMES:
            settings.props.gtk_interface_color_scheme = _SCHEMES[theme]
        else:
            settings.reset_property("gtk-interface-color-scheme")
        self._sync_scheme()

    def _sync_scheme(self):
        # App CSS providers resolve @media (prefers-color-scheme) from their own property, not GtkSettings.
        scheme = Gtk.Settings.get_default().props.gtk_interface_color_scheme
        dark = scheme == Gtk.InterfaceColorScheme.DARK
        self._css.props.prefers_color_scheme = Gtk.InterfaceColorScheme.DARK if dark else Gtk.InterfaceColorScheme.LIGHT


def main() -> int:
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
