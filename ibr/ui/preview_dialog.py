import hashlib
import shutil
import subprocess
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from ..core.fmt import format_size
from ..core.preview import converter_commands
from ..core.settings import xdg_dir
from ..services.runner import in_thread
from .dialog import Dialog
from .widgets import button, hbox, label, vbox


class PreviewDialog(Dialog):
    def __init__(self, parent, path: Path, kind: str):
        super().__init__(parent, path.name, 960, 680)
        self.set_resizable(True)
        self._path = path
        body = vbox(0)
        stage = Gtk.Box(vexpand=True, hexpand=True)
        stage.add_css_class("preview-stage")
        body.append(stage)

        if kind == "image":
            viewer = self._image(path)
            if viewer is None:
                viewer = self._converting(path)
        else:
            viewer = self._media(path)
        stage.append(viewer or self._unsupported())

        bar = hbox(12, "preview-bar")
        info = label(f"{path.name} · {format_size(path.stat().st_size)}", "caption", ellipsize=True)
        info.set_hexpand(True)
        info.set_valign(Gtk.Align.CENTER)
        bar.append(info)
        external = button("Open in Default App", "document-open-symbolic", "outline")
        external.connect("clicked", lambda *_: self._open_external())
        bar.append(external)
        close = button("Close", None, "primary")
        close.connect("clicked", lambda *_: self.close())
        bar.append(close)
        body.append(bar)
        self.set_child(body)

    def _image(self, path: Path) -> Gtk.Widget | None:
        try:
            texture = Gdk.Texture.new_from_filename(str(path))
        except GLib.Error:
            return None
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_hexpand(True)
        picture.set_vexpand(True)
        picture.update_property([Gtk.AccessibleProperty.LABEL], [path.name])
        return picture

    def _converting(self, path: Path) -> Gtk.Widget | None:
        digest = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()[:16]
        target = xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "previews" / f"{digest}.png"
        commands = converter_commands(str(path), str(target), shutil.which)
        if not commands and not target.exists():
            return None
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, hexpand=True, vexpand=True,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)

        def convert() -> bool:
            if target.exists():
                return True
            target.parent.mkdir(parents=True, exist_ok=True)
            for argv in commands:
                try:
                    if subprocess.run(argv, capture_output=True, timeout=60).returncode == 0 and target.exists():
                        return True
                except (OSError, subprocess.TimeoutExpired):
                    pass
                target.unlink(missing_ok=True)
            return False

        def done(ok: bool):
            parent = spinner.get_parent()
            if parent:
                parent.remove(spinner)
                parent.append((self._image(target) if ok else None) or self._unsupported())

        in_thread(convert, done)
        return spinner

    def _media(self, path: Path) -> Gtk.Widget | None:
        stream = Gtk.MediaFile.new_for_filename(str(path))
        if type(stream).__name__ == "GtkNoMediaFile":
            return None
        video = Gtk.Video(media_stream=stream, autoplay=True, hexpand=True, vexpand=True)
        stream.connect("notify::error", lambda s, _p: s.get_error() and self._swap(video))
        return video

    def _unsupported(self) -> Gtk.Widget:
        box = vbox(10)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_hexpand(True)
        icon = Gtk.Image.new_from_icon_name("image-missing-symbolic")
        icon.set_pixel_size(48)
        box.append(icon)
        box.append(label("iBR cannot show this format.", "h3", xalign=0.5))
        box.append(label("Use Open in Default App to view it with your system viewer.", "caption", xalign=0.5))
        return box

    def _swap(self, widget: Gtk.Widget):
        parent = widget.get_parent()
        if parent:
            parent.remove(widget)
            parent.append(self._unsupported())

    def _open_external(self):
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(self._path))).launch(self, None, None)
