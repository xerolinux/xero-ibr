import io
import math
from functools import cache

import cairo
from gi.repository import Gdk, GLib, Gtk, Pango

from .sounds import mark


def label(text: str = "", *classes: str, xalign: float = 0.0, wrap: bool = False,
          ellipsize: bool = False, selectable: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    for css in classes:
        widget.add_css_class(css)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    widget.set_selectable(selectable)
    return widget


def button(text: str = "", icon: str | None = None, *classes: str, tooltip: str | None = None) -> Gtk.Button:
    widget = Gtk.Button()
    mark(widget)
    if icon and text:
        content = Gtk.Box(spacing=8)
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(Gtk.Label(label=text))
        widget.set_child(content)
    elif icon:
        widget.set_icon_name(icon)
        widget.add_css_class("icon")
    else:
        widget.set_label(text)
    for css in classes:
        widget.add_css_class(css)
    if tooltip:
        widget.set_tooltip_text(tooltip)
        widget.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    return widget


def set_button_text(widget: Gtk.Button, text: str):
    child = widget.get_child()
    if isinstance(child, Gtk.Box):
        last = child.get_last_child()
        if isinstance(last, Gtk.Label):
            last.set_label(text)
            return
    widget.set_label(text)


def vbox(spacing: int = 0, *classes: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for css in classes:
        box.add_css_class(css)
    return box


def hbox(spacing: int = 0, *classes: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for css in classes:
        box.add_css_class(css)
    return box


def crumb_bar() -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
    """A path row that scrolls instead of widening the window, kept scrolled to the deepest folder."""
    box = hbox(2)
    scroller = Gtk.ScrolledWindow(child=box, hexpand=True, vscrollbar_policy=Gtk.PolicyType.NEVER)
    adjustment = scroller.get_hadjustment()
    adjustment.connect("changed", lambda a: a.set_value(a.get_upper() - a.get_page_size()))
    return scroller, box


def wrap_row(*widgets: Gtk.Widget) -> Gtk.FlowBox:
    """A button row that wraps onto a second line rather than widening the window."""
    row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
                      max_children_per_line=len(widgets), homogeneous=False)
    row.add_css_class("wrap-row")
    for widget in widgets:
        row.append(widget)
    return row


def clear(box: Gtk.Box):
    while child := box.get_first_child():
        box.remove(child)


def set_classes(widget: Gtk.Widget, *classes: str, keep: tuple[str, ...] = ()):
    widget.set_css_classes([*keep, *classes])


class InfoCard(Gtk.Box):
    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("card")
        self.set_hexpand(True)
        self.append(label(title, "card-label"))
        self.value = label("", "card-value", ellipsize=True)
        self.append(self.value)
        self.sub = label("", "card-sub", ellipsize=True)
        self.append(self.sub)
        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("card-bar")
        self.bar.set_margin_top(6)
        self.bar.set_visible(False)
        self.append(self.bar)

    def update(self, value: str, sub: str = "", fraction: float | None = None):
        self.value.set_label(value)
        self.sub.set_label(sub)
        self.sub.set_visible(bool(sub))
        self.bar.set_visible(fraction is not None)
        if fraction is not None:
            self.bar.set_fraction(max(0.0, min(fraction, 1.0)))


@cache
def letter_tile(letter: str) -> Gdk.Texture:
    """Stand-in for an app icon the backup does not have."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    cr = cairo.Context(surface)
    cr.new_sub_path()
    for x, y, start in ((50, 14, -0.5), (50, 50, 0), (14, 50, 0.5), (14, 14, 1)):
        cr.arc(x, y, 14, start * math.pi, (start + 0.5) * math.pi)
    cr.close_path()
    cr.set_source_rgb(0.36, 0.37, 0.43)
    cr.fill()
    cr.set_source_rgb(0.93, 0.93, 0.96)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(30)
    extents = cr.text_extents(letter)
    cr.move_to(32 - extents.width / 2 - extents.x_bearing, 32 - extents.height / 2 - extents.y_bearing)
    cr.show_text(letter)
    out = io.BytesIO()
    surface.write_to_png(out)
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(out.getvalue()))


def app_texture(data: bytes | None, name: str) -> Gdk.Texture:
    """An app's icon from PNG data, or a letter tile when there is none."""
    if data:
        try:
            return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except GLib.Error:
            pass
    return letter_tile((name[:1] or "?").upper())
