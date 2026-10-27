import queue
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from gi.repository import Gdk, GLib, GObject, Gtk

from ..core.settings import xdg_dir
from ..core.thumbs import THUMB_SIZE, cache_name
from .widgets import hbox, label, vbox

TILE = 132
_WORKERS = 2
_KEEP = 600


def thumbs_dir() -> Path:
    return xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "thumbs"


class ThumbLoader:
    """Makes thumbnails on worker threads, newest request first, and keeps the textures it has loaded.
    produce(target) writes a PNG at target and returns whether it did."""

    def __init__(self):
        self._jobs: queue.LifoQueue = queue.LifoQueue()
        self._textures: OrderedDict[str, Gdk.Texture | None] = OrderedDict()
        self._waiting: dict[str, list[Callable]] = {}
        self._generation = 0
        for _ in range(_WORKERS):
            threading.Thread(target=self._work, daemon=True).start()

    def request(self, key: str, produce: Callable[[Path], bool], callback) -> Gdk.Texture | None:
        if key in self._textures:
            self._textures.move_to_end(key)
            return self._textures[key]
        target = thumbs_dir() / cache_name(key, THUMB_SIZE)
        if target.exists():
            return self._remember(key, self._load(target))
        if key in self._waiting:
            self._waiting[key].append(callback)
            return None
        self._waiting[key] = [callback]
        self._jobs.put((self._generation, key, target, produce))
        return None

    def forget_pending(self):
        """Drops requests for a folder that is no longer shown."""
        self._generation += 1
        self._waiting.clear()

    @staticmethod
    def _load(target: Path) -> Gdk.Texture | None:
        try:
            return Gdk.Texture.new_from_filename(str(target))
        except GLib.Error:
            return None

    def _remember(self, key: str, texture: Gdk.Texture | None) -> Gdk.Texture | None:
        self._textures[key] = texture
        while len(self._textures) > _KEEP:
            self._textures.popitem(last=False)
        return texture

    def _work(self):
        while True:
            generation, key, target, produce = self._jobs.get()
            if generation != self._generation:
                continue
            try:
                made = produce(target)
            except Exception:
                made = False
            GLib.idle_add(self._finished, generation, key, target, made)

    def _finished(self, generation: int, key: str, target: Path, made: bool):
        texture = self._load(target) if made else None
        self._remember(key, texture)
        if generation == self._generation:
            for callback in self._waiting.pop(key, []):
                callback(texture)
        return False


class ViewSwitch(Gtk.Box):
    """List / Grid toggle for a file browser."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, mode: str):
        super().__init__(css_classes=["linked", "view-switch"])
        self._buttons = {}
        group = None
        for name, icon, tooltip in (("list", "view-list-symbolic", "List view"),
                                    ("grid", "view-grid-symbolic", "Grid view")):
            toggle = Gtk.ToggleButton(icon_name=icon, tooltip_text=tooltip, group=group, active=name == mode)
            toggle.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
            toggle.connect("toggled", lambda b, n=name: b.get_active() and self.emit("changed", n))
            group = group or toggle
            self._buttons[name] = toggle
            self.append(toggle)

    def select(self, mode: str):
        self._buttons[mode].set_active(True)


class Tile(Gtk.Box):
    """A grid cell: thumbnail (or icon) with a play badge for videos, then name and size."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["tile"])
        self.item = None
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self.picture.set_size_request(TILE, TILE)
        self.icon = Gtk.Image(pixel_size=48)
        self.badge = hbox(0, "tile-badge")
        self.badge.append(Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=12))
        self.badge.set_halign(Gtk.Align.START)
        self.badge.set_valign(Gtk.Align.END)
        frame = Gtk.Overlay(css_classes=["tile-frame"], overflow=Gtk.Overflow.HIDDEN)
        frame.set_size_request(TILE, TILE)
        frame.set_child(self.picture)
        frame.add_overlay(self.icon)
        frame.add_overlay(self.badge)
        self.append(frame)
        texts = vbox(0)
        self.name = label("", "tile-name", ellipsize=True, xalign=0.5)
        self.name.set_max_width_chars(16)
        self.detail = label("", "tile-detail", xalign=0.5)
        texts.append(self.name)
        texts.append(self.detail)
        self.append(texts)

    def show(self, item, name: str, detail: str, icon: str, texture: Gdk.Texture | None, video: bool = False):
        self.item = item
        self.name.set_label(name)
        self.detail.set_label(detail)
        self.set_texture(texture, icon)
        self.badge.set_visible(video)

    def set_texture(self, texture: Gdk.Texture | None, icon: str):
        self.picture.set_paintable(texture)
        self.picture.set_visible(texture is not None)
        self.icon.set_from_icon_name(icon)
        self.icon.set_visible(texture is None)


def thumb_cell(icon_widget: Gtk.Image) -> Gtk.Widget:
    """The small square in front of a list row's name; shows a thumbnail once one is ready."""
    frame = hbox(0, "row-thumb")
    frame.set_size_request(24, 24)
    frame.set_hexpand(False)
    picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, visible=False)
    picture.set_size_request(24, 24)
    icon_widget.set_size_request(24, 24)
    frame.append(picture)
    frame.append(icon_widget)
    return frame


def set_row_thumb(frame: Gtk.Widget, texture: Gdk.Texture | None, icon: str):
    picture, image = frame.get_first_child(), frame.get_last_child()
    picture.set_paintable(texture)
    picture.set_visible(texture is not None)
    image.set_from_icon_name(icon)
    image.set_visible(texture is None)
