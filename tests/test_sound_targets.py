import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

# GTK 4.24's init_check() says True even with no display, and creating a widget then segfaults (headless CI).
pytestmark = pytest.mark.skipif(not Gtk.init_check() or Gdk.Display.get_default() is None, reason="needs a display")

from ibr.ui.sounds import mark, sound_target  # noqa: E402
from ibr.ui.widgets import button  # noqa: E402


def test_app_buttons_sound_from_their_content():
    widget = button("Update")
    assert sound_target(widget.get_child()) is widget


def test_marked_menu_button_sounds():
    menu = Gtk.MenuButton(icon_name="open-menu-symbolic")
    mark(menu)
    inner = menu.get_first_child()
    assert sound_target(inner) is menu


def test_rows_built_from_plain_buttons_are_silent():
    row = Gtk.Button()
    content = Gtk.Label(label="iPhone 11")
    row.set_child(content)
    assert sound_target(content) is None


def test_switches_and_checkboxes_are_silent():
    assert sound_target(Gtk.Switch()) is None
    assert sound_target(Gtk.CheckButton()) is None
