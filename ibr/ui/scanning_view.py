import math

from gi.repository import Gtk

from .widgets import clear, hbox, label, vbox

PRIMARY = (0x56 / 255, 0x57 / 255, 0xF5 / 255)


class Radar(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_content_width(280)
        self.set_content_height(280)
        self.set_halign(Gtk.Align.CENTER)
        self._angle = 0.0
        self._last = None
        self._tick = 0
        self.animating = True
        self.set_draw_func(self._draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Waiting for an iPhone or iPad"])

    def do_map(self):
        Gtk.DrawingArea.do_map(self)
        self._tick = self.add_tick_callback(self._on_tick)

    def do_unmap(self):
        if self._tick:
            self.remove_tick_callback(self._tick)
            self._tick = 0
        Gtk.DrawingArea.do_unmap(self)

    def _on_tick(self, widget, clock):
        now = clock.get_frame_time() / 1_000_000
        if self.animating and self._last is not None:
            self._angle = (self._angle + (now - self._last) * 1.6) % (2 * math.pi)
            self.queue_draw()
        self._last = now
        return True

    def _draw(self, area, cr, width, height):
        fg = self.get_color()
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 3
        for factor, alpha in ((1.0, 0.08), (0.77, 0.11), (0.53, 0.14)):
            cr.arc(cx, cy, radius * factor, 0, 2 * math.pi)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
            cr.set_line_width(2)
            cr.stroke()
        cr.arc(cx, cy, radius * 0.53, 0, 2 * math.pi)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.04)
        cr.fill()
        if self.animating:
            cr.arc(cx, cy, radius, self._angle, self._angle + math.pi / 2)
            cr.set_source_rgb(*PRIMARY)
            cr.set_line_width(3)
            cr.stroke()
        w, h = 58, 118
        x, y, r = cx - w / 2, cy - h / 2, 14
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(*PRIMARY)
        cr.set_line_width(3)
        cr.set_dash([8, 6])
        cr.stroke()


class ScanningView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.set_margin_start(32)
        self.set_margin_end(32)
        self.radar = Radar()
        self.append(self.radar)
        texts = vbox(6)
        self._title = label("", "h2", xalign=0.5, wrap=True)
        self._subtitle = label("", "body-text", xalign=0.5, wrap=True)
        self._subtitle.set_max_width_chars(60)
        self._subtitle.set_justify(Gtk.Justification.CENTER)
        texts.append(self._title)
        texts.append(self._subtitle)
        self.append(texts)
        self._chips = hbox(12)
        self._chips.set_halign(Gtk.Align.CENTER)
        self.append(self._chips)

    def show(self, title: str, subtitle: str, chips: list[tuple[str, str]], animating: bool = True):
        self._title.set_label(title)
        self._subtitle.set_label(subtitle)
        self.radar.animating = animating
        self.radar.queue_draw()
        clear(self._chips)
        for text, state in chips:
            chip = hbox(8, "chip")
            if state != "todo":
                chip.add_css_class(state)
            icon = {"done": "object-select-symbolic", "fail": "dialog-warning-symbolic"}.get(state)
            if icon:
                chip.append(Gtk.Image.new_from_icon_name(icon))
            else:
                ring = Gtk.Box(valign=Gtk.Align.CENTER)
                ring.add_css_class("todo-ring")
                chip.append(ring)
            chip.append(Gtk.Label(label=text))
            self._chips.append(chip)
