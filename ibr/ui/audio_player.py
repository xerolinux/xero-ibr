import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Gdk, GLib, GObject, Gtk

from ..core.audio_meta import Track
from ..core.fmt import format_size
from ..core.preview import codec_hint
from ..services.media import online_cover, probe
from ..services.runner import in_thread
from .widgets import button, hbox, label, vbox

COVER = 260
_RESTART_AFTER = 3_000_000


@dataclass
class Song:
    """One audio file in the folder; fetch(callback) hands callback a local path, or None when it fails."""
    name: str
    fetch: Callable[[Callable[[Path | None], None]], None]


def clock(microseconds: int) -> str:
    seconds = max(0, microseconds // 1_000_000)
    return f"{seconds // 60}:{seconds % 60:02d}"


class AudioPlayer(Gtk.Box):
    """Cover, tags, seek bar and Previous / Play / Next through the audio files of one folder."""

    __gsignals__ = {"track-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, songs: list[Song], index: int):
        super().__init__(spacing=28, css_classes=["audio-player"])
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(24)
        self._songs = songs
        self._index = index
        self._stream: Gtk.MediaFile | None = None
        self._turn = 0
        self.path: Path | None = None

        left = vbox(12)
        left.set_size_request(COVER, -1)
        left.set_hexpand(False)
        cover = Gtk.Overlay(css_classes=["cover"], overflow=Gtk.Overflow.HIDDEN)
        cover.set_size_request(COVER, COVER)
        self._cover = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, visible=False)
        self._note = Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=96)
        cover.set_child(self._note)
        cover.add_overlay(self._cover)
        left.append(cover)
        self._title = label("", "h2", ellipsize=True)
        self._byline = label("", "subtitle", ellipsize=True)
        texts = vbox(2)
        texts.append(self._title)
        texts.append(self._byline)
        left.append(texts)
        self._seek = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, sensitive=False)
        self._seek.set_range(0, 1)
        self._seek.update_property([Gtk.AccessibleProperty.LABEL], ["Position"])
        self._seek.connect("change-value", self._on_seek)
        times = hbox(0)
        self._elapsed = label("0:00", "caption")
        self._elapsed.set_hexpand(True)
        self._length = label("0:00", "caption")
        times.append(self._elapsed)
        times.append(self._length)
        seek = vbox(2)
        seek.append(self._seek)
        seek.append(times)
        left.append(seek)
        controls = hbox(18)
        controls.set_halign(Gtk.Align.CENTER)
        self._previous = button("", "media-skip-backward-symbolic", "flat", "player-button", tooltip="Previous")
        self._previous.connect("clicked", lambda *_: self._back())
        self._play = button("", "media-playback-pause-symbolic", "primary", "player-play", tooltip="Pause")
        self._play.connect("clicked", lambda *_: self.toggle())
        self._next = button("", "media-skip-forward-symbolic", "flat", "player-button", tooltip="Next")
        self._next.connect("clicked", lambda *_: self.skip(1))
        for widget in (self._previous, self._play, self._next):
            controls.append(widget)
        left.append(controls)
        self.append(left)

        right = vbox(8)
        right.set_hexpand(True)
        self._problem = label("", "warning-box", wrap=True)
        self._problem.set_visible(False)
        right.append(self._problem)
        count = len(songs)
        right.append(label(f"IN THIS FOLDER · {count} TRACK{'S' if count != 1 else ''}", "section-title"))
        self._rows = Gtk.ListBox(css_classes=["playlist"], selection_mode=Gtk.SelectionMode.SINGLE)
        self._rows.connect("row-activated", lambda _l, row: self.load(row.get_index()))
        for song in songs:
            row = hbox(10)
            row.append(Gtk.Image(icon_name="audio-x-generic-symbolic"))
            row.append(label(Path(song.name).stem, ellipsize=True))
            self._rows.append(row)
        right.append(Gtk.ScrolledWindow(child=self._rows, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        right.append(label("DETAILS", "section-title"))
        facts = Gtk.Grid(column_spacing=16, row_spacing=8, css_classes=["card"])
        self._facts = {}
        for row, name in enumerate(("Artist", "Album", "Length", "Format", "Size")):
            facts.attach(label(name, "caption"), 0, row, 1, 1)
            value = label("", ellipsize=True)
            value.set_hexpand(True)
            facts.attach(value, 1, row, 1, 1)
            self._facts[name] = value
        right.append(facts)
        self.append(right)
        self.connect("unrealize", lambda *_: self.stop())
        self.load(index)

    def load(self, index: int):
        self.stop()
        self._turn += 1
        turn = self._turn
        self._index = index
        song = self._songs[index]
        self._rows.select_row(self._rows.get_row_at_index(index))
        self._previous.set_sensitive(True)
        self._next.set_sensitive(index + 1 < len(self._songs))
        self._show(Track(Path(song.name).stem, "", "", 0.0))
        self._set_cover(None)
        self._seek.set_sensitive(False)
        self._seek.set_value(0)
        self._elapsed.set_label("0:00")
        self._length.set_label("0:00")
        self._problem.set_visible(False)
        for value in self._facts.values():
            value.set_label("…")
        song.fetch(lambda path: turn == self._turn and self._start(path, turn))

    def toggle(self):
        if self._stream:
            self._stream.pause() if self._stream.get_playing() else self._stream.play()

    def skip(self, step: int):
        index = self._index + step
        if 0 <= index < len(self._songs):
            self.load(index)

    def stop(self):
        if self._stream:
            self._stream.pause()
            self._stream.set_file(None)
            self._stream = None

    def _back(self):
        if self._stream and self._stream.get_timestamp() > _RESTART_AFTER:
            self._stream.seek(0)
        else:
            self.skip(-1)

    def _start(self, path: Path | None, turn: int):
        if path is None:
            self._warn("This file could not be opened.")
            return
        self.path = path
        self.emit("track-changed", path)
        self._facts["Format"].set_label(path.suffix.lstrip(".").upper() or "Audio")
        self._facts["Size"].set_label(format_size(path.stat().st_size))
        stream = Gtk.MediaFile.new_for_filename(str(path))
        self._stream = stream
        stream.connect("notify::timestamp", self._on_time)
        stream.connect("notify::duration", self._on_time)
        stream.connect("notify::playing", self._on_playing)
        stream.connect("notify::ended", lambda s, _p: s.get_ended() and self.skip(1))
        stream.connect("notify::error", lambda s, _p: s.get_error() and self._warn(
            codec_hint(bool(os.environ.get("APPIMAGE")))))
        stream.play()

        def describe():
            track, cover = probe(path)
            return track, cover or online_cover(track)

        in_thread(describe, lambda result: turn == self._turn and self._described(*result))

    def _warn(self, text: str):
        self._problem.set_label(text)
        self._problem.set_visible(True)

    def _described(self, track: Track, cover: bytes | None):
        self._show(track)
        self._set_cover(cover)

    def _show(self, track: Track):
        self._title.set_label(track.title)
        self._byline.set_label(" · ".join(part for part in (track.artist, track.album) if part) or "Unknown artist")
        self._facts["Artist"].set_label(track.artist or "Unknown")
        self._facts["Album"].set_label(track.album or "Unknown")
        if track.duration:
            self._facts["Length"].set_label(clock(int(track.duration * 1_000_000)))

    def _set_cover(self, data: bytes | None):
        texture = None
        if data:
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except GLib.Error:
                texture = None
        self._cover.set_paintable(texture)
        self._cover.set_visible(texture is not None)
        self._note.set_visible(texture is None)

    def _on_time(self, stream, _pspec):
        duration, now = stream.get_duration(), stream.get_timestamp()
        self._elapsed.set_label(clock(now))
        self._length.set_label(clock(duration))
        self._seek.set_sensitive(duration > 0)
        if duration > 0:
            self._seek.set_value(now / duration)

    def _on_playing(self, stream, _pspec):
        playing = stream.get_playing()
        self._play.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
        self._play.set_tooltip_text("Pause" if playing else "Play")

    def _on_seek(self, scale, _scroll, value):
        if self._stream and self._stream.get_duration() > 0:
            self._stream.seek(int(max(0.0, min(value, 1.0)) * self._stream.get_duration()))
        return False
