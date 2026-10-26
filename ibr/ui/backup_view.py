import os
import shutil
import tempfile
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from ..core.afc import icon_for, media_kind
from ..core.app_catalog import APPLE_APPS, AppMeta, catalog_file, load_saved, save_merged
from ..core.backup_browse import BackupReader, Node, PasswordNeeded, WrongPassword
from ..core.backups import BackupEntry
from ..core.fmt import format_date, format_size
from ..services import keyring
from ..services.runner import in_thread
from ..services.store_icons import fetch_store_icons
from .backup_tree import BackupTree
from .preview_dialog import PreviewDialog
from .widgets import app_texture, button, clear, crumb_bar, hbox, label, vbox

ROOT_LABEL = "Backup"
APP_ICON = 22


class NodeItem(GObject.Object):
    def __init__(self, node: Node, reader: BackupReader, icon_for):
        super().__init__()
        self.node = node
        self._reader = reader
        self._icon_for = icon_for
        self._details = None

    @property
    def icon(self) -> Gdk.Texture | None:
        return self._icon_for(self.node)

    @property
    def details(self):
        if self._details is None and not self.node.is_dir:
            self._details = self._reader.details(self.node)
        return self._details


class BackupView(Gtk.Box):
    __gsignals__ = {
        "close": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "restore": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._window = window
        self.entry: BackupEntry | None = None
        self._reader: BackupReader | None = None
        self._icons: dict[str, Gdk.Texture | None] = {}
        self._path: tuple[str, ...] = ()
        self._heading = ("", "")
        self._asked: set[str] = set()
        self._temp: Path | None = None
        self.busy = False
        self.tree = BackupTree(self._icon_for)
        self.tree.connect("open-path", lambda _t, path: self.open_path(path))
        self.tree.connect("back", lambda *_: self.emit("close"))
        for side, value in (("top", 14), ("bottom", 12), ("start", 18), ("end", 18)):
            getattr(self, f"set_margin_{side}")(value)

        top = hbox(8)
        self._app_icon = Gtk.Image(pixel_size=36, visible=False)
        self._app_icon.set_valign(Gtk.Align.CENTER)
        top.append(self._app_icon)
        titles = vbox(2)
        titles.set_hexpand(True)
        self._title = label("", "h3", ellipsize=True)
        self._subtitle = label("", "row-sub", ellipsize=True)
        titles.append(self._title)
        titles.append(self._subtitle)
        top.append(titles)
        self._up = button("", "ibr-go-parent-symbolic", "flat", "crumb-up", tooltip="Up one level")
        self._up.connect("clicked", lambda *_: self.open_path(self._path[:-1]))
        preview = button("", "view-reveal-symbolic", tooltip="Preview selected file")
        preview.connect("clicked", lambda *_: self._preview_selected())
        save = button("Save to…", "folder-download-symbolic", "primary")
        save.connect("clicked", lambda *_: self._pick_destination())
        restore = button("Restore", "document-revert-symbolic", "outline", tooltip="Restore this backup to a device")
        restore.connect("clicked", lambda *_: self.emit("restore", self.entry))
        self._close = button("", "window-close-symbolic", tooltip="Close backup")
        self._close.connect("clicked", lambda *_: self.emit("close"))
        self._actions = [self._up, preview, save, restore]
        for widget in (preview, save, restore, self._close):
            top.append(widget)
        self.append(top)
        path_row = hbox(6)
        path_row.append(self._up)
        crumbs, self._crumbs = crumb_bar()
        path_row.append(crumbs)
        self.append(path_row)

        self._pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self._pages.add_named(self._build_list(), "list")
        self._pages.add_named(self._build_loading(), "loading")
        self._pages.add_named(self._build_locked(), "locked")
        self.append(self._pages)

        status = hbox(10)
        self._status = label("", "caption", ellipsize=True)
        self._status.set_hexpand(True)
        self._progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, visible=False)
        self._progress.add_css_class("thin")
        self._progress.set_size_request(200, -1)
        status.append(self._status)
        status.append(self._progress)
        self.append(status)

    def _build_list(self) -> Gtk.Widget:
        self._store = Gio.ListStore(item_type=NodeItem)
        self._selection = Gtk.MultiSelection(model=self._store)
        self._list = Gtk.ColumnView(model=self._selection, show_row_separators=True, reorderable=False)
        self._list.add_css_class("files")
        self._list.connect("activate", lambda _v, position: self._activate(self._store.get_item(position)))
        self._column("Name", self._setup_name, self._bind_name, expand=True)
        self._column("Size", self._setup_text, lambda item, cell: cell.set_label(self._size_text(item)), width=120)
        self._column("Modified", self._setup_text, lambda item, cell: cell.set_label(
            format_date(item.details.modified) if item.details and item.details.modified else ""), width=190)
        frame = Gtk.ScrolledWindow(vexpand=True, child=self._list)
        frame.add_css_class("files-frame")
        self._empty = label("", "caption", xalign=0.5)
        self._empty.set_can_target(False)
        overlay = Gtk.Overlay(child=frame)
        overlay.add_overlay(self._empty)
        return overlay

    def _build_loading(self) -> Gtk.Widget:
        box = vbox(12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner(width_request=32, height_request=32)
        box.append(self._spinner)
        self._loading = label("", "body-text", xalign=0.5, wrap=True)
        self._loading.set_max_width_chars(60)
        box.append(self._loading)
        return box

    def _build_locked(self) -> Gtk.Widget:
        box = vbox(12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_size_request(380, -1)
        icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        icon.set_pixel_size(40)
        box.append(icon)
        box.append(label("This backup is encrypted", "h3", xalign=0.5))
        text = label("Enter the backup password to browse its files. Files stay encrypted on disk; only the ones "
                     "you save or preview are decrypted.", "body-text", xalign=0.5, wrap=True)
        text.set_justify(Gtk.Justification.CENTER)
        text.set_max_width_chars(46)
        box.append(text)
        self._password = Gtk.PasswordEntry(show_peek_icon=True, activates_default=False)
        self._password.update_property([Gtk.AccessibleProperty.LABEL], ["Backup password"])
        self._password.connect("activate", lambda *_: self._unlock())
        box.append(self._password)
        self._remember = Gtk.CheckButton(label="Remember in the system keyring")
        box.append(self._remember)
        self._lock_error = label("", "caption", xalign=0.5, wrap=True)
        self._lock_error.add_css_class("device-status")
        self._lock_error.add_css_class("warn")
        box.append(self._lock_error)
        unlock = button("Unlock", None, "primary")
        unlock.set_halign(Gtk.Align.CENTER)
        unlock.connect("clicked", lambda *_: self._unlock())
        box.append(unlock)
        return box

    def _column(self, title: str, setup, bind, expand: bool = False, width: int = -1):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, cell: setup(cell))
        factory.connect("bind", lambda _f, cell: bind(cell.get_item(), cell.get_child()))
        self._list.append_column(Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True,
                                                      fixed_width=width))

    @staticmethod
    def _setup_text(cell):
        cell.set_child(label("", "caption", xalign=0))

    @staticmethod
    def _setup_name(cell):
        row = hbox(10)
        row.append(Gtk.Image(width_request=APP_ICON))
        row.append(label("", ellipsize=True))
        cell.set_child(row)

    @staticmethod
    def _bind_name(item: NodeItem, row: Gtk.Box):
        image, icon = row.get_first_child(), item.icon
        if icon:
            image.set_from_paintable(icon)
            image.set_pixel_size(APP_ICON)
        else:
            image.set_from_icon_name(icon_for(item.node.name, item.node.is_dir))
            image.set_pixel_size(-1)
        row.get_last_child().set_label(item.node.name)

    @staticmethod
    def _size_text(item: NodeItem) -> str:
        if item.node.is_dir:
            count = len(item.node.children)
            return f"{count} item" if count == 1 else f"{count} items"
        return format_size(item.details.size) if item.details else ""

    def _icon_for(self, node: Node) -> Gdk.Texture | None:
        if not node.app or not self._reader:
            return None
        if node.app not in self._icons:
            self._icons[node.app] = app_texture(self._reader.icon(node), node.name)
        return self._icons[node.app]

    def show(self, entry: BackupEntry) -> bool:
        if self.busy:
            return False
        if self.entry is not None and entry.path == self.entry.path and self._reader:
            return True
        self.release()
        self.entry = entry
        when = format_date(entry.local_date) if entry.local_date else "Unknown date"
        self._heading = (f"{entry.device_name} · {when}", "")
        self._title.set_label(self._heading[0])
        self.tree.show_entry(entry.device_name, when)
        details = [entry.os_version or "Unknown version", "Encrypted" if entry.encrypted else "Not encrypted"]
        if entry.damaged:
            details.append("Damaged")
        elif not entry.complete:
            details.append("Incomplete")
        self._heading = (self._heading[0], " · ".join(details))
        self._subtitle.set_label(self._heading[1])
        self._app_icon.set_visible(False)
        self._store.remove_all()
        clear(self._crumbs)
        self._set_actions(False)
        if entry.encrypted:
            saved = keyring.lookup(entry.udid)
            if saved:
                self._open(saved, remember=False, from_keyring=True)
            else:
                self._show_locked("")
        else:
            self._open(None, remember=False, from_keyring=False)
        return True

    def relabel(self, udid: str):
        """Picks up app names and icons saved from the device while this backup is open."""
        if not self._reader or self.busy or self.entry is None or self.entry.udid != udid:
            return
        self._reader.relabel(load_saved(catalog_file(udid)))
        self._icons.clear()
        self.tree.load(self._reader)
        path = self._path
        while path and self._reader.find(path) is None:
            path = path[:-1]
        self.open_path(path)

    def _fill_icons(self):
        """Apps the backup and device gave no icon for get their App Store artwork, saved for next time."""
        entry, reader = self.entry, self._reader
        missing = {n.app: APPLE_APPS.get(n.app, (n.name,))[0] for n in reader.listing(("Apps",))
                   if n.app and n.app not in self._asked and reader.icon(n) is None}
        if not missing:
            return
        self._asked.update(missing)

        def work():
            icons = fetch_store_icons(sorted(missing))
            if not icons:
                return False
            try:
                save_merged(catalog_file(entry.udid), {bid: AppMeta(missing[bid], icon) for bid, icon in icons.items()})
            except OSError:
                return False
            return True

        in_thread(work, lambda saved: saved and self.relabel(entry.udid))

    def release(self):
        if self.busy:
            return
        if self._reader:
            self._reader.close()
        self._reader = None
        self._icons = {}
        self.tree.clear()
        self.entry = None
        self._password.set_text("")
        if self._temp:
            shutil.rmtree(self._temp, ignore_errors=True)
            self._temp = None

    def _set_actions(self, sensitive: bool):
        for widget in self._actions:
            widget.set_sensitive(sensitive)
        self._up.set_sensitive(sensitive and bool(self._path))

    def _show_locked(self, error: str):
        self._lock_error.set_label(error)
        self._lock_error.set_visible(bool(error))
        self._pages.set_visible_child_name("locked")
        self._status.set_label("")
        self._password.grab_focus()

    def _unlock(self):
        password = self._password.get_text()
        if not password:
            self._show_locked("Enter the backup password.")
            return
        self._open(password, self._remember.get_active(), from_keyring=False)

    def _open(self, password: str | None, remember: bool, from_keyring: bool):
        entry = self.entry
        self._loading.set_label("Unlocking the backup…" if password else "Reading the backup…")
        self._spinner.start()
        self._pages.set_visible_child_name("loading")

        def work():
            try:
                return BackupReader.open(entry.path, password, load_saved(catalog_file(entry.udid))), None
            except PasswordNeeded:
                return None, ""
            except WrongPassword:
                return None, ("The saved password did not unlock this backup. Enter it again." if from_keyring
                              else "That password did not unlock this backup.")
            except Exception as error:
                return None, error

        def done(result):
            reader, error = result
            self._spinner.stop()
            if entry is not self.entry:
                if reader:
                    reader.close()
                return
            if isinstance(error, str):
                self._show_locked(error)
                return
            if error is not None:
                self._loading.set_label(f"This backup cannot be read: {error}")
                return
            if remember:
                keyring.store(entry.udid, entry.device_name, password)
            self._password.set_text("")
            self._reader = reader
            self._pages.set_visible_child_name("list")
            self.tree.load(reader)
            self.open_path(())
            self._fill_icons()

        in_thread(work, done)

    def open_path(self, path: tuple[str, ...]):
        if not self._reader:
            return
        self._path = path
        nodes = self._reader.listing(path)
        items = [NodeItem(node, self._reader, self._icon_for) for node in nodes]
        self._store.splice(0, self._store.get_n_items(), items)
        self._empty.set_label("" if nodes else "This folder is empty.")
        self._render_crumbs()
        self._set_actions(not self.busy)
        self._status.set_label(f"{len(nodes)} items")
        self._render_heading()
        self.tree.reveal(path)

    def _render_heading(self):
        app = self._reader.find(self._path[:2]) if self._path[:1] == ("Apps",) and len(self._path) > 1 else None
        icon = self._icon_for(app) if app and app.app else None
        self._app_icon.set_visible(icon is not None)
        if icon is not None:
            self._app_icon.set_from_paintable(icon)
            self._title.set_label(app.name)
            self._subtitle.set_label(f"{app.app} · {self._heading[0]}")
        else:
            self._title.set_label(self._heading[0])
            self._subtitle.set_label(self._heading[1])

    def _render_crumbs(self):
        clear(self._crumbs)
        for depth in range(len(self._path) + 1):
            crumb = button(self._path[depth - 1] if depth else ROOT_LABEL, None, "flat", "crumb")
            crumb.connect("clicked", lambda _b, target=self._path[:depth]: self.open_path(target))
            if depth:
                self._crumbs.append(label("›", "caption"))
            self._crumbs.append(crumb)

    def _selected(self) -> list[Node]:
        bitset = self._selection.get_selection()
        return [self._store.get_item(bitset.get_nth(i)).node for i in range(bitset.get_size())]

    def _activate(self, item: NodeItem):
        if item.node.is_dir:
            self.open_path((*self._path, item.node.name))
        else:
            self._preview(item.node)

    def _preview_selected(self):
        files = [node for node in self._selected() if not node.is_dir]
        if files:
            self._preview(files[0])
        else:
            self._status.set_label("Select a file first.")

    def _preview(self, node: Node):
        if self.busy:
            return
        if self._temp is None:
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            self._temp = Path(tempfile.mkdtemp(prefix="ibr-backup-", dir=runtime if runtime else None))
        folder = Path(tempfile.mkdtemp(dir=self._temp))
        kind = media_kind(node.name, False)

        def opened(result):
            if not result.saved:
                return
            path = result.saved[0]
            if kind in ("image", "video", "audio"):
                PreviewDialog(self._window, path, kind).present()
            else:
                Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self._window, None, None)

        self._run_export([node], folder, "Opening", opened)

    def _pick_destination(self):
        selected = self._selected()
        if not selected:
            self._status.set_label("Select files or folders first.")
            return
        dialog = Gtk.FileDialog(title="Save to folder", modal=True)

        def chosen(source, result):
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return
            self._run_export(selected, Path(folder.get_path()), "Saving", None)

        dialog.select_folder(self._window, None, chosen)

    def _run_export(self, nodes: list[Node], dest: Path, verb: str, then):
        reader = self._reader
        self.busy = True
        self._set_actions(False)
        self._close.set_sensitive(False)
        self._progress.set_fraction(0)
        self._progress.set_visible(True)

        def progress(index: int, total: int, name: str):
            def update():
                self._progress.set_fraction(index / max(total, 1))
                self._status.set_label(f"{verb} {index + 1} of {total}: {name}")
            GLib.idle_add(update)

        def work():
            try:
                return reader.export(nodes, dest, progress), None
            except Exception as error:
                return None, str(error)

        def done(outcome):
            result, error = outcome
            self.busy = False
            self._progress.set_visible(False)
            self._close.set_sensitive(True)
            self._set_actions(True)
            if error:
                self._status.set_label(f"Failed: {error}")
                return
            note = f" {result.missing} files were not in the backup." if result.missing else ""
            if then:
                self._status.set_label(note.strip() or "Done")
                then(result)
            else:
                count = len(result.saved)
                self._status.set_label(f"Saved {count} file{'s' if count != 1 else ''} to {dest}.{note}")

        in_thread(work, done)
