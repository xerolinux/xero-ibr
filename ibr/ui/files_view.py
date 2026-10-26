import tempfile
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from ..core.afc import (AfcError, RemoteEntry, SharingApp, breadcrumbs, child_path, icon_for, location_root,
                        media_kind, parent_path)
from ..core.app_catalog import catalog_file, load_saved
from ..core.fmt import format_date, format_size
from ..core.settings import xdg_dir
from ..services.afc import Afc, list_sharing_apps
from ..services.homescreen import refresh_app_catalog
from ..services.runner import in_thread
from .dialog import confirm
from .preview_dialog import PreviewDialog
from .widgets import app_texture, button, clear, crumb_bar, hbox, label, vbox

MEDIA = "Media"
APP_ICON = 20


class EntryItem(GObject.Object):
    def __init__(self, entry: RemoteEntry, path: str):
        super().__init__()
        self.entry = entry
        self.path = path


def _download_queue(afc: Afc, remotes: list[str], target: Path, on_item, on_done):
    """Downloads one path at a time; on_item(index, name) before each, on_done(paths, error) at the end."""
    downloaded: list[Path] = []

    def step(index: int):
        if index == len(remotes):
            on_done(downloaded, None)
            return
        on_item(index, remotes[index].rsplit("/", 1)[-1])

        def got(path, error):
            if error:
                on_done(downloaded, error)
                return
            downloaded.append(path)
            step(index + 1)

        afc.download(remotes[index], target, got)

    step(0)


class LazyDownload(Gdk.ContentProvider):
    """Drag source content: files are fetched from the device only when the drop target asks for them."""

    def __init__(self, view: "FilesView", remotes: list[str]):
        super().__init__()
        self._view = view
        self._remotes = remotes

    def do_ref_formats(self):
        return Gdk.ContentFormats.new(["text/uri-list"])

    def do_write_mime_type_async(self, mime_type, stream, io_priority, cancellable, callback, *data):
        staging = Path(tempfile.mkdtemp(prefix="drag-", dir=self._view.staging_root()))

        def finished(paths, error):
            self._view.transfer_done(error)
            uris = "".join(f"{Gio.File.new_for_path(str(p)).get_uri()}\r\n" for p in paths)
            stream.write_bytes_async(GLib.Bytes.new(uris.encode()), io_priority, None,
                                     lambda s, r: (s.write_bytes_finish(r), s.close_async(io_priority, None, None)))

        self._view.transfer_started(len(self._remotes), "Copying from device")
        _download_queue(self._view.afc, self._remotes, staging, self._view.transfer_item, finished)

    def do_write_mime_type_finish(self, result):
        return True


class FilesView(Gtk.Box):
    __gsignals__ = {"close": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, window):
        super().__init__(spacing=0)
        self._window = window
        self.afc: Afc | None = None
        self._udid = None
        self._path = "/"
        self._root = "/"
        self._busy = False
        self._app_icons: dict[str, Gdk.Texture] = {}

        locations = vbox(8, "sidebar", "files-locations")
        locations.set_size_request(200, -1)
        back = button("Back to device", "go-previous-symbolic", "flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.emit("close"))
        locations.append(back)
        locations.append(label("LOCATIONS", "section-title"))
        self._media = self._location_button("Photos and Media", "drive-harddisk-symbolic", None)
        locations.append(self._media)
        locations.append(label("APPS WITH FILE SHARING", "section-title"))
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._apps = vbox(4)
        scroller.set_child(self._apps)
        locations.append(scroller)
        self.append(locations)

        main = vbox(12)
        main.set_hexpand(True)
        for side, value in (("top", 14), ("bottom", 12), ("start", 16), ("end", 16)):
            getattr(main, f"set_margin_{side}")(value)
        toolbar = hbox(8)
        self._title_icon = Gtk.Image(pixel_size=32, visible=False)
        toolbar.append(self._title_icon)
        self._title = label("", "h3", ellipsize=True)
        self._title.set_hexpand(True)
        toolbar.append(self._title)
        self._up = button("", "go-up-symbolic", tooltip="Parent folder")
        self._up.connect("clicked", lambda *_: self.open_path(parent_path(self._path)))
        new_folder = button("", "folder-new-symbolic", tooltip="New folder")
        new_folder.connect("clicked", lambda *_: self._new_folder())
        self._new_folder_button = new_folder
        preview = button("", "view-reveal-symbolic", tooltip="Preview selected photo or video")
        preview.connect("clicked", lambda *_: self._preview_selected())
        upload = button("Add Files", "list-add-symbolic", "primary")
        upload.connect("clicked", lambda *_: self._pick_upload())
        download = button("Save to…", "folder-download-symbolic", "outline")
        download.connect("clicked", lambda *_: self._pick_download())
        delete = button("", "user-trash-symbolic", tooltip="Delete selected")
        delete.connect("clicked", lambda *_: self._delete())
        refresh = button("", "view-refresh-symbolic", tooltip="Refresh")
        refresh.connect("clicked", lambda *_: self.open_path(self._path))
        self._actions = [self._up, new_folder, preview, upload, download, delete, refresh]
        for widget in self._actions:
            toolbar.append(widget)
        main.append(toolbar)
        crumbs, self._crumbs = crumb_bar()
        main.append(crumbs)

        self._store = Gio.ListStore(item_type=EntryItem)
        self._selection = Gtk.MultiSelection(model=self._store)
        self._list = Gtk.ColumnView(model=self._selection, show_row_separators=True, reorderable=False)
        self._list.add_css_class("files")
        self._list.connect("activate", self._on_activate)
        self._add_column("Name", self._bind_name, expand=True)
        self._add_column("Size", lambda item, cell: cell.set_label(
            "" if item.entry.is_dir else format_size(item.entry.size)))
        self._add_column("Modified", lambda item, cell: cell.set_label(
            format_date(item.entry.modified) if item.entry.modified else ""), width=190)
        frame = Gtk.ScrolledWindow(vexpand=True)
        frame.add_css_class("files-frame")
        frame.set_child(self._list)
        self._empty = label("", "caption", xalign=0.5)
        overlay = Gtk.Overlay(child=frame)
        overlay.add_overlay(self._empty)
        self._empty.set_can_target(False)
        main.append(overlay)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        frame.add_controller(drop)

        status = hbox(10)
        self._status = label("", "caption", ellipsize=True)
        self._status.set_hexpand(True)
        self._progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self._progress.add_css_class("thin")
        self._progress.set_size_request(200, -1)
        self._progress.set_visible(False)
        status.append(self._status)
        status.append(self._progress)
        main.append(status)
        self.append(main)

    def staging_root(self) -> Path:
        folder = xdg_dir("XDG_CACHE_HOME", ".cache") / "ibr" / "transfers"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _location_button(self, title: str, icon: str | Gdk.Texture, app: SharingApp | None) -> Gtk.Button:
        if isinstance(icon, str):
            widget = button(title, icon, "flat", "location")
        else:
            widget = Gtk.Button(css_classes=["flat", "location"])
            content = hbox(8)
            content.append(Gtk.Image(paintable=icon, pixel_size=APP_ICON))
            content.append(label(title, ellipsize=True))
            widget.set_child(content)
        widget.get_child().set_halign(Gtk.Align.START)
        widget.app = app
        widget.connect("clicked", lambda *_: self._select_location(app))
        return widget

    def _app_buttons(self) -> list[Gtk.Button]:
        children, child = [], self._apps.get_first_child()
        while child:
            if isinstance(child, Gtk.Button):
                children.append(child)
            child = child.get_next_sibling()
        return children

    def _add_column(self, title: str, bind, expand: bool = False, width: int = -1):
        factory = Gtk.SignalListItemFactory()
        if bind == self._bind_name:
            factory.connect("setup", self._setup_name)
        else:
            factory.connect("setup", lambda _f, cell: cell.set_child(label("", "caption", xalign=0)))
        factory.connect("bind", lambda _f, cell: bind(cell.get_item(), cell.get_child()))
        column = Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True, fixed_width=width)
        self._list.append_column(column)

    def _setup_name(self, factory, cell):
        row = hbox(10)
        row.append(Gtk.Image())
        row.append(label("", ellipsize=True))
        source = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        source.connect("prepare", self._on_drag_prepare, cell)
        row.add_controller(source)
        cell.set_child(row)

    def _bind_name(self, item: EntryItem, row: Gtk.Box):
        row.get_first_child().set_from_icon_name(icon_for(item.entry.name, item.entry.is_dir))
        row.get_last_child().set_label(item.entry.name)

    def show_device(self, udid: str, name: str):
        if udid != self._udid:
            self._udid = udid
            self._device_name = name
            self._select_location(None)
            self._load_apps()

    def _load_apps(self):
        clear(self._apps)
        self._apps.append(label("Loading…", "caption"))
        udid = self._udid

        def work():
            try:
                apps = list_sharing_apps(udid)
            except Exception as error:
                return [], {}, str(error)
            saved = load_saved(catalog_file(udid))
            if any(not (saved.get(app.bundle_id) and saved[app.bundle_id].icon) for app in apps):
                refresh_app_catalog(udid)
                saved = load_saved(catalog_file(udid))
            return apps, {bid: meta.icon for bid, meta in saved.items()}, None

        def loaded(result):
            apps, icons, error = result
            if udid != self._udid:
                return
            clear(self._apps)
            if error or not apps:
                self._apps.append(label(error or "No installed apps share files.", "caption", wrap=True))
            self._app_icons = {app.bundle_id: app_texture(icons.get(app.bundle_id), app.name) for app in apps}
            for app in apps:
                self._apps.append(self._location_button(app.name, self._app_icons[app.bundle_id], app))

        in_thread(work, loaded)

    def _select_location(self, app: SharingApp | None):
        for widget in [self._media, *self._app_buttons()]:
            widget.remove_css_class("active")
        active = next((b for b in self._app_buttons() if b.app is app), self._media) if app else self._media
        active.add_css_class("active")
        self.afc = Afc(self._udid, app.bundle_id if app else None)
        self._location_name = app.name if app else MEDIA
        icon = self._app_icons.get(app.bundle_id) if app else None
        self._title_icon.set_visible(icon is not None)
        if icon is not None:
            self._title_icon.set_from_paintable(icon)
        self._root = location_root(app.bundle_id if app else None)
        self.open_path(self._root)

    def open_path(self, path: str):
        self._path = path
        self._render_crumbs()
        self._set_status("Loading…")
        afc = self.afc

        def listed(entries, error):
            if afc is not self.afc or path != self._path:
                return
            self._store.remove_all()
            if error:
                self._empty.set_label(f"Cannot open this folder: {error}")
                self._set_status("")
                return
            entries = [entry for entry in entries if not entry.name.startswith(".")]
            for entry in entries:
                self._store.append(EntryItem(entry, child_path(path, entry.name)))
            self._empty.set_label("" if entries else "Empty folder. Drop files here to copy them to the device.")
            self._set_status(f"{len(entries)} items")

        afc.list(path, listed)

    def _render_crumbs(self):
        clear(self._crumbs)
        self._title.set_label(self._location_name)
        self._up.set_sensitive(self._path != self._root)
        for index, (part, target) in enumerate(breadcrumbs(self._path, self._root, self._location_name)):
            crumb = button(part, None, "flat", "crumb")
            crumb.connect("clicked", lambda _b, t=target: self.open_path(t))
            if index:
                self._crumbs.append(label("›", "caption"))
            self._crumbs.append(crumb)

    def _selected(self) -> list[EntryItem]:
        bitset = self._selection.get_selection()
        return [self._store.get_item(bitset.get_nth(i)) for i in range(bitset.get_size())]

    def _on_activate(self, view, position):
        item = self._store.get_item(position)
        if item.entry.is_dir:
            self.open_path(item.path)
        else:
            self._preview(item)

    def _preview_selected(self):
        files = [item for item in self._selected() if not item.entry.is_dir]
        if files:
            self._preview(files[0])
        else:
            self._set_status("Select a photo or video first.")

    def _preview(self, item: EntryItem):
        if self._busy:
            return
        kind = media_kind(item.entry.name, False)
        folder = self.staging_root() / "preview"
        folder.mkdir(parents=True, exist_ok=True)
        self.transfer_started(1, "Opening")
        self.transfer_item(0, item.entry.name)

        def fetched(paths, error):
            self.transfer_done(error)
            if not error and paths:
                if kind in ("image", "video", "audio"):
                    PreviewDialog(self._window, paths[0], kind).present()
                else:
                    Gtk.FileLauncher.new(Gio.File.new_for_path(str(paths[0]))).launch(self._window, None, None)

        _download_queue(self.afc, [item.path], folder, lambda *_: None, fetched)

    def _on_drag_prepare(self, source, x, y, cell):
        item = cell.get_item()
        if item is None or self._busy:
            return None
        selected = self._selected()
        remotes = [i.path for i in selected] if item in selected else [item.path]
        icon = Gtk.IconTheme.get_for_display(self.get_display()).lookup_icon(
            icon_for(item.entry.name, item.entry.is_dir), None, 32, 1, Gtk.TextDirection.NONE, 0)
        source.set_icon(icon, 0, 0)
        return LazyDownload(self, remotes)

    def _on_drop(self, target, value, x, y):
        files = [Path(f.get_path()) for f in value.get_files() if f.get_path()]
        if files and not self._busy:
            self._upload(files)
            return True
        return False

    def _set_status(self, text: str):
        self._status.set_label(text)

    def transfer_started(self, count: int, verb: str):
        self._busy = True
        self._verb, self._count = verb, count
        self._progress.set_fraction(0)
        self._progress.set_visible(True)
        for widget in self._actions:
            widget.set_sensitive(False)

    def transfer_item(self, index: int, name: str):
        self._progress.set_fraction(index / max(self._count, 1))
        self._set_status(f"{self._verb} {index + 1} of {self._count}: {name}")

    def transfer_done(self, error: str | None):
        self._busy = False
        self._progress.set_visible(False)
        for widget in self._actions:
            widget.set_sensitive(True)
        self._up.set_sensitive(self._path != self._root)
        self._set_status(f"Failed: {error}" if error else "Done")

    def _upload(self, files: list[Path]):
        self.transfer_started(len(files), "Copying to device")
        afc, folder = self.afc, self._path

        def step(index: int):
            if index == len(files):
                self.transfer_done(None)
                self.open_path(folder)
                return
            self.transfer_item(index, files[index].name)

            def sent(_result, error):
                if error:
                    self.transfer_done(error)
                    self.open_path(folder)
                else:
                    step(index + 1)

            afc.upload(files[index], folder, sent)

        step(0)

    def _pick_upload(self):
        dialog = Gtk.FileDialog(title="Add files to the device", modal=True)

        def chosen(source, result):
            try:
                files = source.open_multiple_finish(result)
            except GLib.Error:
                return
            paths = [Path(f.get_path()) for f in files if f.get_path()]
            if paths:
                self._upload(paths)

        dialog.open_multiple(self._window, None, chosen)

    def _pick_download(self):
        selected = self._selected()
        if not selected:
            self._set_status("Select files or folders first.")
            return
        dialog = Gtk.FileDialog(title="Save to folder", modal=True)

        def chosen(source, result):
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return
            remotes = [item.path for item in selected]
            self.transfer_started(len(remotes), "Copying from device")
            _download_queue(self.afc, remotes, Path(folder.get_path()), self.transfer_item,
                            lambda _paths, error: self.transfer_done(error))

        dialog.select_folder(self._window, None, chosen)

    def _new_folder(self):
        popover = Gtk.Popover()
        box = hbox(8)
        entry = Gtk.Entry(placeholder_text="Folder name", activates_default=True)
        create = button("Create", None, "primary")
        box.append(entry)
        box.append(create)
        popover.set_child(box)
        popover.set_parent(self._new_folder_button)

        def make(*_):
            name = entry.get_text().strip()
            popover.popdown()
            if not name:
                return
            try:
                path = child_path(self._path, name)
            except AfcError as error:
                self._set_status(str(error))
                return
            self.afc.mkdir(path, lambda _r, error: self._set_status(f"Failed: {error}") if error
                           else self.open_path(self._path))

        create.connect("clicked", make)
        entry.connect("activate", make)
        popover.connect("closed", lambda p: p.unparent())
        popover.popup()
        entry.grab_focus()

    def _delete(self):
        selected = self._selected()
        if not selected:
            self._set_status("Select files or folders first.")
            return
        names = ", ".join(item.entry.name for item in selected[:3]) + ("…" if len(selected) > 3 else "")

        def answered(ok):
            if ok:
                self.afc.remove([item.path for item in selected],
                                lambda _r, error: (self._set_status(f"Failed: {error}") if error else None,
                                                   self.open_path(self._path)))

        confirm(self._window, f"Delete {len(selected)} item(s) from the device?",
                f"{names} will be removed from the device. This cannot be undone.", "Delete", answered,
                destructive=True)
