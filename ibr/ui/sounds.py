from importlib.resources import files

from gi.repository import Gtk

from ..core.sounds import SoundGate

# Opt-in: rows, tiles and cards are often Gtk.Button underneath, but only real buttons should tick.
SOUND_CLASS = "has-sound"
_FILES = {"hover": "hover.wav", "click": "click.wav", "matrix": "matrix.ogg"}
_playing: set[Gtk.MediaFile] = set()


def _play(name: str):
    # A fresh stream each time: re-seeking an ended stream swallows the start of these short clips.
    # Never call set_volume(): PipeWire stores it per application and it then also quiets the music player.
    media = Gtk.MediaFile.new_for_filename(str(files("ibr") / "data" / "sounds" / _FILES[name]))
    _playing.add(media)
    for prop in ("notify::ended", "notify::error"):
        media.connect(prop, lambda m, _p: _playing.discard(m))
    media.play()


gate = SoundGate(_play)


def mark(widget: Gtk.Widget):
    widget.add_css_class(SOUND_CLASS)


def sound_target(widget: Gtk.Widget | None) -> Gtk.Widget | None:
    while widget is not None:
        if widget.has_css_class(SOUND_CLASS):
            return widget if widget.is_sensitive() else None
        widget = widget.get_parent()
    return None


def _target_at(window: Gtk.Window, x: float, y: float) -> Gtk.Widget | None:
    return sound_target(window.pick(x, y, Gtk.PickFlags.DEFAULT))


def attach(window: Gtk.Window):
    motion = Gtk.EventControllerMotion(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    motion.connect("motion", lambda _c, x, y: gate.hover(_target_at(window, x, y)))
    motion.connect("leave", lambda _c: gate.hover(None))
    window.add_controller(motion)
    # Pressed, not released: the button's own gesture claims the press and cancels ours before release.
    press = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    press.connect("pressed", lambda _g, _n, x, y: _target_at(window, x, y) and gate.click())
    window.add_controller(press)
