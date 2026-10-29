from gi.repository import Gio, GObject, Gtk

from ..core.backup_browse import BackupReader, Node, tree_sections
from .sounds import mark
from .widgets import hbox, label

ICON = 18
PLACES = {
    "Camera Roll": ("camera-photo-symbolic", "image-x-generic-symbolic"),
    "On My iPhone": ("phone-apple-iphone-symbolic", "phone-symbolic"),
    "On My iPad": ("computer-apple-ipad-symbolic", "tablet-symbolic"),
    "Home": ("user-home-symbolic", "go-home-symbolic"),
    "Media": ("folder-music-symbolic", "audio-x-generic-symbolic"),
}


class TreeItem(GObject.Object):
    def __init__(self, path: tuple[str, ...], node: Node | None = None, title: str = "",
                 members: list[Node] | None = None):
        super().__init__()
        self.path = path
        self.node = node
        self.title = title
        self.members = members or []


def _place(item: TreeItem) -> bool:
    return len(item.path) == 1 and item.path[0] in PLACES


def _folders(item: TreeItem) -> Gio.ListStore | None:
    if item.node is None or not item.node.is_dir or _place(item):
        return None
    folders = sorted((n for n in item.node.children.values() if n.is_dir), key=lambda n: n.name.casefold())
    if not folders:
        return None
    store = Gio.ListStore(item_type=TreeItem)
    store.splice(0, 0, [TreeItem((*item.path, n.name), n) for n in folders])
    return store


class BackupTree(Gtk.Box):
    """The sidebar shown while a backup is open: its places, apps and system data as a folder tree."""

    __gsignals__ = {
        "open-path": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "back": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, icon_for):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("sidebar")
        self.add_css_class("backup-tree")
        self.set_size_request(270, -1)
        self._icon_for = icon_for
        self._syncing = False

        back = Gtk.Button(tooltip_text="Back to devices")
        back.add_css_class("flat")
        back.add_css_class("tree-back")
        mark(back)
        back.update_property([Gtk.AccessibleProperty.LABEL], ["Back to devices"])
        content = hbox(8)
        content.append(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        names = hbox(8)
        self._name = label("", "device-name", ellipsize=True)
        self._when = label("", "device-status", ellipsize=True)
        names.append(self._name)
        names.append(self._when)
        content.append(names)
        back.set_child(content)
        back.connect("clicked", lambda *_: self.emit("back"))
        self.append(back)

        self._search = Gtk.SearchEntry(placeholder_text="Filter apps and folders")
        self._search.update_property([Gtk.AccessibleProperty.LABEL], ["Filter apps and folders"])
        self._search.connect("search-changed", lambda *_: self._filter.changed(Gtk.FilterChange.DIFFERENT))
        self.append(self._search)

        self._roots = Gio.ListStore(item_type=TreeItem)
        self._filter = Gtk.CustomFilter.new(self._matches)
        filtered = Gtk.FilterListModel(model=self._roots, filter=self._filter)
        self._tree = Gtk.TreeListModel.new(filtered, False, False, _folders)
        self._selection = Gtk.SingleSelection(model=self._tree, autoselect=False, can_unselect=True)
        self._selection.connect("notify::selected", self._on_selected)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup)
        factory.connect("bind", self._bind)
        self._list = Gtk.ListView(model=self._selection, factory=factory)
        self._list.update_property([Gtk.AccessibleProperty.LABEL], ["Backup folders"])
        self.append(Gtk.ScrolledWindow(child=self._list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))

    def show_entry(self, name: str, when: str):
        self._name.set_label(name)
        self._when.set_label(when)
        self.clear()

    def clear(self):
        self._search.set_text("")
        self._roots.remove_all()

    def load(self, reader: BackupReader):
        items = []
        for section in tree_sections(reader):
            if not section.nodes:
                continue
            items.append(TreeItem(section.path, title=section.title, members=section.nodes))
            items.extend(TreeItem((*section.path, n.name), n) for n in section.nodes)
        self._roots.splice(0, self._roots.get_n_items(), items)

    def reveal(self, path: tuple[str, ...]):
        """Selects the row for path, expanding its parents, without opening it again."""
        self._syncing = True
        found = Gtk.INVALID_LIST_POSITION
        index = 0
        while index < self._tree.get_n_items():
            row = self._tree.get_row(index)
            item = row.get_item()
            if item.path == path:
                found = index
                break
            if item.node is not None and len(item.path) < len(path) and path[:len(item.path)] == item.path:
                row.set_expanded(True)
            index += 1
        self._selection.set_selected(found)
        if found != Gtk.INVALID_LIST_POSITION:
            self._list.scroll_to(found, Gtk.ListScrollFlags.NONE, None)
        self._syncing = False

    def _matches(self, item: TreeItem) -> bool:
        text = self._search.get_text().strip().casefold()
        names = [n.name for n in item.members] if item.node is None else [item.node.name]
        return not text or any(text in name.casefold() for name in names)

    def _on_selected(self, selection, _pspec):
        row = selection.get_selected_item()
        if row is not None and not self._syncing:
            self.emit("open-path", row.get_item().path)

    @staticmethod
    def _setup(_factory, cell):
        expander = Gtk.TreeExpander()
        row = hbox(8)
        row.append(Gtk.Image(width_request=ICON))
        name = label("", ellipsize=True, xalign=0)
        name.set_hexpand(True)
        row.append(name)
        row.append(label("", "caption"))
        expander.set_child(row)
        cell.set_child(expander)

    def _bind(self, _factory, cell):
        expander = cell.get_child()
        tree_row = cell.get_item()
        item = tree_row.get_item()
        expander.set_list_row(tree_row)
        image = expander.get_child().get_first_child()
        name = image.get_next_sibling()
        count = name.get_next_sibling()
        header = item.node is None
        flat = header or _place(item)
        expander.set_hide_expander(flat)
        expander.set_indent_for_icon(not flat)
        for widget in (cell.get_child(), name):
            if header:
                widget.add_css_class("tree-header")
            else:
                widget.remove_css_class("tree-header")
        image.set_visible(not header)
        count.set_visible(header)
        if header:
            name.set_label(item.title.upper())
            count.set_label(str(len(item.members)))
            return
        name.set_label(item.node.name)
        icon = self._icon_for(item.node)
        if icon:
            image.set_from_paintable(icon)
            image.set_pixel_size(ICON)
        else:
            names = [*PLACES[item.path[0]], "folder-symbolic"] if _place(item) else ["folder-symbolic"]
            image.set_from_gicon(Gio.ThemedIcon.new_from_names(names))
            image.set_pixel_size(-1)
