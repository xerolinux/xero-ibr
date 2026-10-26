from gi.repository import Gtk, Pango


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
