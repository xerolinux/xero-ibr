import io
import math
from pathlib import Path

import cairo
from gi.repository import Gtk

from ..core.catalog import ModelSpec
from ..core.settings import xdg_dir

_PACKAGED_IMAGES = Path(__file__).resolve().parent.parent / "data" / "devices"


def image_for(product_type: str | None) -> Path | None:
    """Official renders dropped in as <ProductType>.png replace the drawing."""
    if not product_type:
        return None
    for folder in (xdg_dir("XDG_DATA_HOME", ".local/share") / "ibr" / "device-images", _PACKAGED_IMAGES):
        candidate = folder / f"{product_type}.png"
        if candidate.is_file():
            return candidate
    return None


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _mix(a, b, t: float):
    return tuple(x + (y - x) * t for x, y in zip(a, b, strict=True))


def _luma(c) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _rrect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _fill(cr, color, alpha: float = 1.0):
    cr.set_source_rgba(*color, alpha)
    cr.fill()


WHITE, BLACK = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
FLASH = (0.93, 0.90, 0.80)
SENSOR = (0.05, 0.05, 0.06)


class DeviceArt(Gtk.DrawingArea):
    def __init__(self, width: int, height: int):
        super().__init__()
        self.set_content_width(width)
        self.set_content_height(height)
        self._spec: ModelSpec | None = None
        self._finish = "#3a3a3c"
        self._image: cairo.ImageSurface | None = None
        self._home = None
        self.set_draw_func(self._draw)

    def set_device(self, spec: ModelSpec | None, finish: str | None = None, product_type: str | None = None):
        self._spec = spec
        self._finish = finish or (spec.finish if spec else "#3a3a3c")
        path = image_for(product_type)
        try:
            self._image = cairo.ImageSurface.create_from_png(str(path)) if path else None
        except (cairo.Error, OSError):
            self._image = None
        self.update_property([Gtk.AccessibleProperty.LABEL], [spec.name if spec else ""])
        self.queue_draw()

    def set_home(self, home):
        """home: HomeScreenImage read from the connected device; None shows the screen off."""
        if home is None:
            self._home = None
        else:
            def surface(data):
                try:
                    return cairo.ImageSurface.create_from_png(io.BytesIO(data))
                except (cairo.Error, MemoryError):
                    return None

            def icons(entries):
                return [(icon.bundle_id is None, [s for s in map(surface, pngs) if s]) for icon, pngs in entries]

            self._home = (surface(home.wallpaper) if home.wallpaper else None, icons(home.dock), icons(home.apps))
        self.queue_draw()

    def _draw(self, area, cr, width, height):
        if self._image is not None:
            self._draw_image(cr, width, height)
            return
        spec = self._spec
        if not spec:
            return
        finish = _rgb(self._finish)
        if height < 90:
            scale = min(width / spec.width_mm, height / spec.height_mm)
            w, h = spec.width_mm * scale, spec.height_mm * scale
            self._front(cr, spec, (width - w) / 2, (height - h) / 2, scale, finish, detailed=False)
            return
        offset = 0.5 if spec.kind != "ipad" else 0.32
        pad = 2.0
        scale = min(width / (spec.width_mm * (1 + offset) + 2 * pad), height / (spec.height_mm * 1.05 + 2 * pad))
        w, h = spec.width_mm * scale, spec.height_mm * scale
        left = (width - w * (1 + offset)) / 2
        top = (height - h * 1.05) / 2
        self._back(cr, spec, left, top, scale, finish)
        front_x, front_y = left + w * offset, top + h * 0.05
        self._shadow(cr, front_x, front_y, w, h, spec.corner_mm * scale)
        self._front(cr, spec, front_x, front_y, scale, finish, detailed=True)

    def _draw_image(self, cr, width, height):
        image = self._image
        scale = min(width / image.get_width(), height / image.get_height())
        cr.translate((width - image.get_width() * scale) / 2, (height - image.get_height() * scale) / 2)
        cr.scale(scale, scale)
        cr.set_source_surface(image, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST)
        cr.paint()

    @staticmethod
    def _shadow(cr, x, y, w, h, r):
        for step in range(6, 0, -1):
            grow = step * 1.6
            _rrect(cr, x - grow + 3, y - grow + 6, w + 2 * grow, h + 2 * grow, r + grow)
            _fill(cr, BLACK, 0.045)

    def _back(self, cr, spec, x, y, scale, finish):
        w, h = spec.width_mm * scale, spec.height_mm * scale
        r = spec.corner_mm * scale
        gradient = cairo.LinearGradient(x, y, x + w, y + h)
        gradient.add_color_stop_rgb(0, *_mix(finish, WHITE, 0.12))
        gradient.add_color_stop_rgb(1, *_mix(finish, BLACK, 0.18))
        _rrect(cr, x, y, w, h, r)
        cr.set_source(gradient)
        cr.fill()
        _rrect(cr, x + 0.5, y + 0.5, w - 1, h - 1, r)
        cr.set_source_rgba(1, 1, 1, 0.16)
        cr.set_line_width(1)
        cr.stroke()
        self._cameras(cr, spec, x, y, scale, finish)

    @staticmethod
    def _cameras(cr, spec, x, y, s, finish):
        bump = _mix(finish, WHITE, 0.08)

        def module(mx, my, mw, mh, radius, color=bump):
            _rrect(cr, x + mx * s, y + my * s, mw * s, mh * s, radius * s)
            _fill(cr, color)
            _rrect(cr, x + mx * s + 0.5, y + my * s + 0.5, mw * s - 1, mh * s - 1, radius * s)
            cr.set_source_rgba(1, 1, 1, 0.12)
            cr.set_line_width(1)
            cr.stroke()

        def lens(cx, cy, radius):
            cr.arc(x + cx * s, y + cy * s, radius * s, 0, 2 * math.pi)
            _fill(cr, _mix(finish, BLACK, 0.55))
            cr.arc(x + cx * s, y + cy * s, radius * 0.74 * s, 0, 2 * math.pi)
            _fill(cr, (0.03, 0.03, 0.05))
            cr.arc(x + cx * s, y + cy * s, radius * 0.38 * s, 0, 2 * math.pi)
            _fill(cr, (0.10, 0.12, 0.22))
            cr.arc(x + (cx - radius * 0.25) * s, y + (cy - radius * 0.25) * s, radius * 0.14 * s, 0, 2 * math.pi)
            _fill(cr, WHITE, 0.35)

        def dot(cx, cy, radius, color):
            cr.arc(x + cx * s, y + cy * s, radius * s, 0, 2 * math.pi)
            _fill(cr, color)

        layout, width = spec.camera, spec.width_mm
        if layout == "ipad_pro":
            module(6, 6, 30, 30, 8)
            lens(14, 14, 5.2)
            lens(14, 28, 5.2)
            dot(28, 14, 2.4, SENSOR)
            dot(28, 26, 1.6, FLASH)
        elif layout == "single" and spec.kind == "ipad":
            lens(10, 10, 3.6)
        elif layout == "single":
            lens(10, 10, 4.2)
            dot(19.5, 10, 1.6, FLASH)
        elif layout == "dual_horizontal":
            module(4.5, 5, 26, 11, 5.5)
            lens(10, 10.5, 4.2)
            lens(24.5, 10.5, 4.2)
            dot(34, 10.5, 1.5, FLASH)
        elif layout == "dual_pill":
            module(5, 5, 12, 25, 6)
            lens(11, 11, 4.4)
            lens(11, 24, 4.4)
            dot(21, 11, 1.5, FLASH)
        elif layout in ("dual_square_vertical", "dual_square_diagonal"):
            module(4.5, 4.5, 30, 30, 7.5)
            lens(12.5, 12.5, 5.2)
            lens(12.5 if layout == "dual_square_vertical" else 26.5, 26.5, 5.2)
            dot(26.5, 12.5, 1.8, FLASH)
        elif layout == "triple":
            module(4, 4, 37, 38, 9)
            lens(13, 13, 6.2)
            lens(13, 33, 6.2)
            lens(30.5, 23, 6.2)
            dot(31, 10, 1.8, FLASH)
            dot(31.5, 35, 2.0, SENSOR)
        elif layout == "plateau_pro":
            module(1.5, 3.5, width - 3, 36, 9)
            lens(12, 12.5, 6.0)
            lens(12, 30.5, 6.0)
            lens(28, 21.5, 6.0)
            dot(width - 12, 13, 1.8, FLASH)
            dot(width - 12, 29, 2.0, SENSOR)
        elif layout == "plateau_air":
            module(2, 4, width - 4, 19, 9.5, (0.06, 0.06, 0.07))
            lens(13, 13.5, 5.4)
            dot(27, 13.5, 2.6, SENSOR)
            dot(36, 13.5, 1.6, FLASH)

    def _front(self, cr, spec, ox, oy, scale, finish, detailed: bool):
        w, h = spec.width_mm * scale, spec.height_mm * scale
        if detailed:
            self._buttons(cr, spec, ox, oy, w, h, scale, _mix(finish, BLACK, 0.18))
        _rrect(cr, ox, oy, w, h, spec.corner_mm * scale)
        _fill(cr, finish)
        _rrect(cr, ox + 0.5, oy + 0.5, w - 1, h - 1, spec.corner_mm * scale)
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.set_line_width(1)
        cr.stroke()

        rim = 0.8 * scale
        light_front = spec.cutout in ("home", "ipad_home") and _luma(finish) > 0.62
        glass = (0.93, 0.93, 0.94) if light_front else (0.04, 0.04, 0.045)
        gx, gy, gw, gh = ox + rim, oy + rim, w - 2 * rim, h - 2 * rim
        glass_r = max(spec.corner_mm * scale - rim, 1)
        _rrect(cr, gx, gy, gw, gh, glass_r)
        _fill(cr, glass)

        sx, sy, sw, sh, sr = self._screen_rect(spec, gx, gy, gw, gh, glass_r, scale)
        if detailed and self._home:
            self._home_screen(cr, spec, sx, sy, sw, sh, sr)
        else:
            self._screen_off(cr, sx, sy, sw, sh, sr)
        self._front_details(cr, spec, gx, gy, gw, gh, sx, sy, sw, sh, scale, glass, light_front)

    @staticmethod
    def _screen_rect(spec, gx, gy, gw, gh, glass_r, scale):
        if spec.cutout == "home":
            side, vertical = gw * 0.055, gh * 0.125
            return gx + side, gy + vertical, gw - 2 * side, gh - 2 * vertical, 0.4 * scale
        if spec.cutout == "ipad_home":
            side, vertical = 9.0 * scale, 19.0 * scale
            return gx + side, gy + vertical, gw - 2 * side, gh - 2 * vertical, 0.6 * scale
        bezel = spec.bezel_mm * scale
        return gx + bezel, gy + bezel, gw - 2 * bezel, gh - 2 * bezel, max(glass_r - bezel, 1.5 * scale)

    def _home_screen(self, cr, spec, x, y, w, h, r):
        wallpaper, dock, apps = self._home
        cr.save()
        _rrect(cr, x, y, w, h, r)
        cr.clip()
        if wallpaper:
            fit = max(w / wallpaper.get_width(), h / wallpaper.get_height())
            cr.save()
            cr.translate(x + (w - wallpaper.get_width() * fit) / 2, y + (h - wallpaper.get_height() * fit) / 2)
            cr.scale(fit, fit)
            cr.set_source_surface(wallpaper, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
            cr.restore()
        else:
            self._screen_off(cr, x, y, w, h, r)
        columns = 6 if spec.kind == "ipad" else 4
        size = w / (columns + (columns + 1) * 0.42)
        gap = size * 0.42
        dock_h = size * 1.5 if dock else 0
        top = y + h * (0.075 if spec.cutout in ("island", "notch") else 0.04)
        rows = max(1, int((y + h - dock_h - h * 0.05 - top) // (size * 1.38)))
        for index, tile in enumerate(apps[: columns * rows]):
            column, row = index % columns, index // columns
            self._icon(cr, tile, x + gap + column * (size + gap), top + row * size * 1.38, size)
        if dock:
            count = min(len(dock), columns)
            dock_w = count * size + (count + 1) * gap
            dx, dy = x + (w - dock_w) / 2, y + h - dock_h - h * 0.025
            _rrect(cr, dx, dy, dock_w, dock_h, dock_h * 0.32)
            _fill(cr, WHITE, 0.22)
            for index, tile in enumerate(dock[:count]):
                self._icon(cr, tile, dx + gap + index * (size + gap), dy + (dock_h - size) / 2, size)
        cr.restore()

    @staticmethod
    def _icon(cr, tile, x, y, size):
        is_folder, surfaces = tile
        radius = size * 0.225
        cr.save()
        _rrect(cr, x, y, size, size, radius)
        cr.clip()
        if is_folder:
            _rrect(cr, x, y, size, size, radius)
            _fill(cr, WHITE, 0.3)
            mini = size * 0.32
            for index, surface in enumerate(surfaces[:4]):
                mx = x + size * 0.13 + (index % 2) * (mini + size * 0.1)
                my = y + size * 0.13 + (index // 2) * (mini + size * 0.1)
                DeviceArt._paint(cr, surface, mx, my, mini)
        elif surfaces:
            DeviceArt._paint(cr, surfaces[0], x, y, size)
        else:
            _rrect(cr, x, y, size, size, radius)
            _fill(cr, WHITE, 0.35)
        cr.restore()

    @staticmethod
    def _paint(cr, surface, x, y, size):
        cr.save()
        cr.translate(x, y)
        cr.scale(size / surface.get_width(), size / surface.get_height())
        cr.set_source_surface(surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    @staticmethod
    def _screen_off(cr, x, y, w, h, r):
        gradient = cairo.LinearGradient(x, y, x, y + h)
        gradient.add_color_stop_rgb(0, 0.09, 0.09, 0.11)
        gradient.add_color_stop_rgb(1, 0.03, 0.03, 0.04)
        _rrect(cr, x, y, w, h, r)
        cr.set_source(gradient)
        cr.fill()
        cr.save()
        _rrect(cr, x, y, w, h, r)
        cr.clip()
        cr.move_to(x + w * 0.35, y)
        cr.line_to(x + w, y)
        cr.line_to(x + w, y + h * 0.42)
        cr.line_to(x, y + h * 0.95)
        cr.line_to(x, y + h * 0.55)
        cr.close_path()
        sheen = cairo.LinearGradient(x, y, x + w, y + h * 0.6)
        sheen.add_color_stop_rgba(0, 1, 1, 1, 0.07)
        sheen.add_color_stop_rgba(1, 1, 1, 1, 0.0)
        cr.set_source(sheen)
        cr.fill()
        cr.restore()

    @staticmethod
    def _front_details(cr, spec, gx, gy, gw, gh, sx, sy, sw, sh, scale, glass, light_front):
        cx = gx + gw / 2
        sensor = (0.45, 0.45, 0.48) if light_front else (0.12, 0.12, 0.14)
        if spec.cutout == "island":
            iw, ih = sw * 0.29, sh * 0.043
            _rrect(cr, cx - iw / 2, sy + sh * 0.014, iw, ih, ih / 2)
            _fill(cr, BLACK)
        elif spec.cutout == "notch":
            nw, nh = sw * 0.44, sh * 0.034
            r = nh * 0.45
            x0 = cx - nw / 2
            cr.move_to(x0, sy)
            cr.line_to(x0 + nw, sy)
            cr.line_to(x0 + nw, sy + nh - r)
            cr.arc(x0 + nw - r, sy + nh - r, r, 0, math.pi / 2)
            cr.line_to(x0 + r, sy + nh)
            cr.arc(x0 + r, sy + nh - r, r, math.pi / 2, math.pi)
            cr.close_path()
            _fill(cr, glass)
        elif spec.cutout == "home":
            speaker_w = gw * 0.16
            _rrect(cr, cx - speaker_w / 2, gy + (sy - gy) * 0.48, speaker_w, 0.9 * scale, 0.45 * scale)
            _fill(cr, sensor)
            cr.arc(cx - gw * 0.14, gy + (sy - gy) * 0.52, 0.9 * scale, 0, 2 * math.pi)
            _fill(cr, sensor)
            DeviceArt._home_button(cr, cx, sy + sh + (gy + gh - sy - sh) / 2, gh * 0.04, light_front, scale)
        elif spec.cutout == "ipad_home":
            cr.arc(cx, gy + (sy - gy) / 2, 1.1 * scale, 0, 2 * math.pi)
            _fill(cr, sensor)
            DeviceArt._home_button(cr, cx, sy + sh + (gy + gh - sy - sh) / 2, 5.2 * scale, light_front, scale)
        else:
            if spec.landscape_camera:
                cr.arc(gx + gw - (gx + gw - sx - sw) / 2, gy + gh / 2, 1.0 * scale, 0, 2 * math.pi)
            else:
                cr.arc(cx, gy + (sy - gy) / 2, 1.0 * scale, 0, 2 * math.pi)
            _fill(cr, sensor)

    @staticmethod
    def _home_button(cr, x, y, r, light_front, scale):
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.set_source_rgb(*((0.88, 0.88, 0.9) if light_front else (0.07, 0.07, 0.08)))
        cr.fill_preserve()
        cr.set_source_rgb(*((0.62, 0.62, 0.66) if light_front else (0.3, 0.3, 0.33)))
        cr.set_line_width(max(0.35 * scale, 1))
        cr.stroke()

    @staticmethod
    def _buttons(cr, spec, ox, oy, w, h, scale, color):
        depth = 0.9 * scale
        cr.set_source_rgb(*color)

        def left(top, length):
            _rrect(cr, ox - depth * 0.8, oy + h * top, depth * 1.6, h * length, depth * 0.5)
            cr.fill()

        def right(top, length):
            _rrect(cr, ox + w - depth * 0.8, oy + h * top, depth * 1.6, h * length, depth * 0.5)
            cr.fill()

        def top_edge(start, length):
            _rrect(cr, ox + w * start, oy - depth * 0.8, w * length, depth * 1.6, depth * 0.5)
            cr.fill()

        if spec.kind == "ipad":
            top_edge(0.78, 0.08)
            right(0.06, 0.05)
            right(0.125, 0.05)
            return
        if spec.cutout == "home":
            left(0.12, 0.035)
            left(0.19, 0.06)
            left(0.265, 0.06)
            right(0.2, 0.075)
            return
        left(0.155, 0.045 if spec.action_button else 0.03)
        left(0.235, 0.075)
        left(0.325, 0.075)
        right(0.25, 0.11)
        if spec.camera_control:
            cr.set_source_rgb(*_mix(color, (0.15, 0.15, 0.17), 0.6))
            right(0.6, 0.075)
