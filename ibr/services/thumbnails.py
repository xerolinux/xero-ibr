import os
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

import gi

from ..core.afc import media_kind
from ..core.preview import converter_commands
from ..core.settings import xdg_dir
from ..core.thumbs import load_thumbnailers, thumbnailer_argv, thumbnailer_for
from .media import probe, video_frame

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GdkPixbuf, GLib  # noqa: E402


@cache
def _system_thumbnailers():
    data = [xdg_dir("XDG_DATA_HOME", ".local/share")]
    data += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    return load_thumbnailers([folder / "thumbnailers" for folder in data])


def _scaled(pixbuf: GdkPixbuf.Pixbuf, size: int) -> GdkPixbuf.Pixbuf:
    width, height = pixbuf.get_width(), pixbuf.get_height()
    scale = min(1.0, size / max(width, height, 1))
    if scale == 1.0:
        return pixbuf
    return pixbuf.scale_simple(max(1, round(width * scale)), max(1, round(height * scale)),
                               GdkPixbuf.InterpType.BILINEAR)


def _from_bytes(data: bytes) -> GdkPixbuf.Pixbuf | None:
    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
    except GLib.Error:
        return None
    return loader.get_pixbuf()


def _from_file(path: Path, size: int) -> GdkPixbuf.Pixbuf | None:
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)
    except GLib.Error:
        return None


def _converted(path: Path, size: int, work: Path) -> GdkPixbuf.Pixbuf | None:
    target = work / "converted.png"
    for argv in converter_commands(str(path), str(target), shutil.which):
        try:
            if subprocess.run(argv, capture_output=True, timeout=60).returncode == 0 and target.exists():
                return _from_file(target, size)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _system(path: Path, name: str, size: int, work: Path) -> GdkPixbuf.Pixbuf | None:
    content_type, _ = Gio.content_type_guess(name, None)
    entry = thumbnailer_for(_system_thumbnailers(), Gio.content_type_get_mime_type(content_type) or "", shutil.which)
    if entry is None:
        return None
    target = work / "system.png"
    try:
        subprocess.run(thumbnailer_argv(entry, str(path), str(target), size), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _from_file(target, size) if target.exists() else None


def can_render(name: str) -> bool:
    if media_kind(name, False):
        return True
    content_type, _ = Gio.content_type_guess(name, None)
    mime = Gio.content_type_get_mime_type(content_type) or ""
    return thumbnailer_for(_system_thumbnailers(), mime, shutil.which) is not None


def render(path: Path, name: str, target: Path, size: int) -> bool:
    """Blocking: writes a PNG thumbnail of a local file, at most size pixels on its longer side."""
    kind = media_kind(name, False)
    with tempfile.TemporaryDirectory(prefix="ibr-thumb-") as work:
        work = Path(work)
        pixbuf = None
        if kind == "image":
            pixbuf = _from_file(path, size) or _converted(path, size, work)
        elif kind == "video":
            frame = video_frame(path)
            pixbuf = _from_bytes(frame) if frame else None
        elif kind == "audio":
            cover = probe(path)[1]
            pixbuf = _from_bytes(cover) if cover else None
        pixbuf = pixbuf or _system(path, name, size, work)
        if pixbuf is None:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        try:
            _scaled(pixbuf, size).savev(str(partial), "png", [], [])
            partial.replace(target)
        except (GLib.Error, OSError):
            partial.unlink(missing_ok=True)
            return False
    return True
