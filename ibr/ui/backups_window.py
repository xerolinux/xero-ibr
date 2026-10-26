from gi.repository import Gio, Gtk

from ..core.fmt import format_date
from ..core.snapshots import delete_backup
from ..services.runner import in_thread
from .dialog import PANEL, Dialog, confirm
from .widgets import button, clear, hbox, label, vbox


class BackupsWindow(Dialog):
    def __init__(self, window, focus_udid: str | None = None):
        super().__init__(window, "Manage Backups", *PANEL)
        self._window = window
        self._focus = focus_udid
        body = vbox(14)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(22)
        top = hbox(10)
        top.append(label("Saved backups", "h3", xalign=0))
        top.get_first_child().set_hexpand(True)
        open_folder = button("Open Backup Folder", "folder-open-symbolic", "outline")
        open_folder.connect("clicked", lambda *_: self._show(window.settings.backup_dir))
        top.append(open_folder)
        body.append(top)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._list = vbox(16)
        scroller.set_child(self._list)
        body.append(scroller)
        self.set_child(body)
        self.refresh()

    def refresh(self):
        clear(self._list)
        groups: dict[str, list] = {}
        for entry in self._window.backups:
            groups.setdefault(entry.udid, []).append(entry)
        if not groups:
            self._list.append(label("No backups yet.", "empty-box", xalign=0.5))
            return
        order = sorted(groups, key=lambda udid: udid != self._focus)
        for udid in order:
            entries = groups[udid]
            section = vbox(8)
            section.append(label(entries[0].device_name.upper(), "section-title"))
            group = vbox(0, "settings-group")
            for entry in entries:
                group.append(self._row(entry))
            section.append(group)
            self._list.append(section)

    def _row(self, entry):
        row = hbox(12, "settings-row")
        text = vbox(2)
        text.set_hexpand(True)
        when = format_date(entry.local_date) if entry.local_date else "Unknown date"
        text.append(label(when, "row-title"))
        details = [entry.os_version or "Unknown version", self._window.size_of(entry) or "…",
                   "Encrypted" if entry.encrypted else "Not encrypted"]
        if entry.damaged:
            details.append("Damaged")
        elif not entry.complete:
            details.append("Incomplete")
        text.append(label(" · ".join(details), "row-sub"))
        row.append(text)
        show = button("", "folder-open-symbolic", "flat", tooltip="Show in file manager")
        show.connect("clicked", lambda *_: self._show(str(entry.path)))
        row.append(show)
        delete = button("", "user-trash-symbolic", "flat", tooltip="Delete this backup")
        delete.set_sensitive(not self._window.operation_active)
        delete.connect("clicked", lambda *_: self._delete(entry))
        row.append(delete)
        return row

    def _show(self, path: str):
        Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self, None, None)

    def _delete(self, entry):
        when = format_date(entry.local_date) if entry.local_date else "unknown date"

        def answered(accepted):
            if not accepted or self._window.operation_active:
                return
            root = self._window.settings.backup_dir
            in_thread(lambda: delete_backup(root, entry), lambda _: self._window.reload_backups(self.refresh))

        confirm(self, "Delete this backup?", f"The backup of {entry.device_name} from {when} is removed "
                "from this computer. This cannot be undone.", "Delete", answered, destructive=True)
