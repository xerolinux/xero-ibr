import threading
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import gi

from .. import __version__
from ..core.audio_meta import Track, artwork_query, itunes_artwork, track_from_tags
from ..core.settings import xdg_dir
from ..core.thumbs import cache_name

gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils  # noqa: E402

_HEADERS = {"User-Agent": f"iBR/{__version__}"}
_lock = threading.Lock()
_ready = False


def _gst() -> bool:
    global _ready
    with _lock:
        if not _ready:
            _ready = Gst.init_check(None)[0]
    return _ready


def _uri(path: Path) -> str:
    return Path(path).resolve().as_uri()


def probe(path: Path) -> tuple[Track, bytes | None]:
    """Blocking: a file's title, artist, album, length and embedded cover art."""
    name = Path(path).name
    if not _gst():
        return track_from_tags({}, name, 0.0), None
    try:
        info = GstPbutils.Discoverer.new(10 * Gst.SECOND).discover_uri(_uri(path))
    except Exception:
        return track_from_tags({}, name, 0.0), None
    lists = [stream.get_tags() for stream in info.get_stream_list()]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        lists.append(info.get_tags())
    tags, cover = {}, None
    for taglist in filter(None, lists):
        for key in ("title", "artist", "album"):
            found, value = taglist.get_string(key)
            if found and value and key not in tags:
                tags[key] = value
        for key in ("image", "preview-image"):
            found, sample = taglist.get_sample(key)
            if found and cover is None:
                buffer = sample.get_buffer()
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if ok:
                    cover = bytes(mapped.data)
                    buffer.unmap(mapped)
    duration = info.get_duration() / Gst.SECOND if info.get_duration() else 0.0
    return track_from_tags(tags, name, duration), cover


def online_cover(track: Track) -> bytes | None:
    """Blocking: cover art from the iTunes Store for tracks without their own, cached on disk."""
    query = artwork_query(track)
    if query is None:
        return None
    cached = xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "covers" / cache_name(track.artist, track.album, track.title)
    if cached.exists():
        return cached.read_bytes() or None
    try:
        request = urllib.request.Request("https://itunes.apple.com/search?" + urllib.parse.urlencode(query),
                                         headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=15) as response:
            url = itunes_artwork(response.read(), track.artist)
        data = b""
        if url:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=15) as response:
                data = response.read()
    except OSError:
        return None
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass
    return data or None


def video_frame(path: Path) -> bytes | None:
    """Blocking: a PNG of the frame one second into a video (or its first frame when shorter)."""
    if not _gst():
        return None
    playbin = Gst.ElementFactory.make("playbin", None)
    if playbin is None:
        return None
    for prop in ("video-sink", "audio-sink"):
        playbin.set_property(prop, Gst.ElementFactory.make("fakesink", None))
    playbin.set_property("uri", _uri(path))
    try:
        playbin.set_state(Gst.State.PAUSED)
        if playbin.get_state(10 * Gst.SECOND)[0] != Gst.StateChangeReturn.SUCCESS:
            return None
        ok, length = playbin.query_duration(Gst.Format.TIME)
        if ok and length > 2 * Gst.SECOND:
            playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, Gst.SECOND)
            playbin.get_state(10 * Gst.SECOND)
        sample = playbin.emit("convert-sample", Gst.Caps.from_string("image/png"))
        if sample is None:
            return None
        buffer = sample.get_buffer()
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            return bytes(mapped.data)
        finally:
            buffer.unmap(mapped)
    finally:
        playbin.set_state(Gst.State.NULL)
