import hashlib
import os
import plistlib
import re
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap
from cryptography.hazmat.primitives.padding import PKCS7

from .app_catalog import APPLE_APPS, AppMeta

TOP_LEVEL = ("Home", "Media", "On My iPad", "Camera Roll", "On My iPhone", "Apps", "System")
_LIBRARY = ("Camera Roll", "On My iPhone", "On My iPad", "Home", "Media")
_LOCAL_STORAGE = ("AppDomainGroup-group.com.apple.FileProvider.LocalStorage", "File Provider Storage")
_FIXED = {"CameraRollDomain": ("Camera Roll",), "HomeDomain": ("Home",), "MediaDomain": ("Media",)}
_GROUP_PREFIX = re.compile(r"^(group\.|systemgroup\.|[A-Z0-9]{10}\.groups\.|[A-Z0-9]{10}\.)")
_CLASS_TAGS = {b"CLAS", b"WRAP", b"WPKY", b"KTYP", b"PBKY"}
_WRAP_PASSCODE = 2
_FILE, _DIR = 1, 2
_CHUNK = 1 << 20


class PasswordNeeded(Exception):
    pass


class WrongPassword(Exception):
    pass


@dataclass(slots=True)
class Node:
    name: str
    is_dir: bool
    file_id: str | None = None
    children: dict[str, "Node"] | None = None
    app: str | None = None


@dataclass(frozen=True)
class Section:
    title: str
    path: tuple[str, ...]
    nodes: list[Node]


@dataclass(frozen=True)
class Details:
    size: int
    modified: datetime | None
    key: bytes | None


@dataclass
class ExportResult:
    saved: list[Path] = field(default_factory=list)
    missing: int = 0


def _owner(ident: str, apps: dict[str, AppMeta]) -> tuple[str, str] | None:
    """The named app an extension or group belongs to, with the id prefix that matched it."""
    best = None
    for bid in apps:
        for key in (bid, *APPLE_APPS.get(bid, ("", ()))[1]):
            if (ident == key or ident.startswith(key + ".")) and (best is None or len(key) > len(best[1])):
                best = (bid, key)
    if best:
        return best
    parts = ident.split(".")
    if len(parts) < 2 or parts[:2] == ["com", "apple"]:
        return None
    vendor = ".".join(parts[:2]) + "."
    found = [bid for bid in apps if bid.startswith(vendor)]
    return (found[0], "") if len(found) == 1 else None


def _place(domain: str, apps: dict[str, AppMeta]) -> tuple[tuple[str, ...], str | None]:
    if domain in _FIXED:
        return _FIXED[domain], None
    if domain.startswith("AppDomain-"):
        bid = domain[len("AppDomain-"):]
        if bid in apps:
            return ("Apps", apps[bid].name), bid
        if bid.startswith("com.apple."):
            return ("System", "Apple Services", bid), None
        return ("Apps", bid), bid
    if domain.startswith("AppDomainPlugin-"):
        ident = domain[len("AppDomainPlugin-"):]
        owner = _owner(ident, apps)
        if owner is None:
            return ("System", "Extensions", ident), None
        bid, key = owner
        short = ident[len(key) + 1:] if key and ident.startswith(key + ".") else ident
        return ("Apps", apps[bid].name, "Extensions", short), bid
    if domain.startswith("AppDomainGroup-"):
        ident = domain[len("AppDomainGroup-"):]
        owner = _owner(_GROUP_PREFIX.sub("", ident), apps)
        if owner is None:
            return ("System", "Shared Groups", ident), None
        return ("Apps", apps[owner[0]].name, "Shared", ident), owner[0]
    return ("System", domain), None


def domain_folder(domain: str, apps: dict[str, AppMeta]) -> tuple[str, ...]:
    return _place(domain, apps)[0]


def app_catalog(info: dict, saved: dict[str, AppMeta]) -> dict[str, AppMeta]:
    """Names and icons by bundle id from the backup's own app list, names saved from the device's Home Screen
    (shorter than store titles, so they win) and Apple's built-in apps. Shared names get their bundle id added."""
    found = {bid: AppMeta(name, None) for bid, (name, _) in APPLE_APPS.items()}
    found.update(saved)
    for bundle_id, app in (info.get("Applications") or {}).items():
        try:
            name = plistlib.loads(app["iTunesMetadata"]).get("itemName")
        except Exception:
            continue
        if isinstance(name, str) and name.strip():
            icon = app.get("PlaceholderIcon")
            known = saved.get(bundle_id)
            found[bundle_id] = AppMeta(known.name if known else name.strip(),
                                       icon if isinstance(icon, bytes) else known.icon if known else None)
    found = {bid: AppMeta(m.name.replace("/", "-"), m.icon) for bid, m in found.items()}
    counts: dict[str, int] = {}
    for meta in found.values():
        counts[meta.name] = counts.get(meta.name, 0) + 1
    return {bid: AppMeta(f"{m.name} ({bid})", m.icon) if counts[m.name] > 1 else m for bid, m in found.items()}


def tree_sections(reader: "BackupReader") -> list[Section]:
    """The backup sidebar's groups: the device's own places, then apps, then system data."""
    top = reader.listing(())
    return [Section("Library", (), [n for n in top if n.name in _LIBRARY]),
            Section("Apps", ("Apps",), reader.listing(("Apps",))),
            Section("System", ("System",), reader.listing(("System",)))]


def _keybag(data: bytes) -> tuple[dict, dict[int, dict]]:
    attrs: dict = {}
    classes: dict[int, dict] = {}
    current = None
    pos = 0
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        length = struct.unpack(">L", data[pos + 4:pos + 8])[0]
        value = data[pos + 8:pos + 8 + length]
        pos += 8 + length
        if length == 4:
            value = struct.unpack(">L", value)[0]
        if tag == b"UUID" and b"UUID" in attrs:
            if current and b"CLAS" in current:
                classes[current[b"CLAS"]] = current
            current = {b"UUID": value}
        elif current is not None and tag in _CLASS_TAGS:
            current[tag] = value
        else:
            attrs[tag] = value
    if current and b"CLAS" in current:
        classes[current[b"CLAS"]] = current
    return attrs, classes


def _unlock(keybag: bytes, password: str) -> dict[int, bytes]:
    attrs, classes = _keybag(keybag)
    key = password.encode()
    if b"DPSL" in attrs:
        key = hashlib.pbkdf2_hmac("sha256", key, attrs[b"DPSL"], attrs[b"DPIC"], 32)
    key = hashlib.pbkdf2_hmac("sha1", key, attrs[b"SALT"], attrs[b"ITER"], 32)
    keys = {}
    for cls, entry in classes.items():
        if b"WPKY" in entry and entry.get(b"WRAP", 0) & _WRAP_PASSCODE:
            try:
                keys[cls] = aes_key_unwrap(key, entry[b"WPKY"])
            except InvalidUnwrap:
                raise WrongPassword from None
    return keys


def _unwrap(keys: dict[int, bytes], blob: bytes) -> bytes:
    return aes_key_unwrap(keys[struct.unpack("<L", blob[:4])[0]], blob[4:])


def _decryptor(key: bytes):
    return Cipher(algorithms.AES(key), modes.CBC(b"\0" * 16)).decryptor()


def _details(blob: bytes) -> Details:
    archive = plistlib.loads(blob)
    objects = archive["$objects"]
    root = objects[archive["$top"]["root"].data]
    key = root.get("EncryptionKey")
    if isinstance(key, plistlib.UID):
        key = objects[key.data]
    if isinstance(key, dict):
        key = key.get("NS.data")
    stamp = root.get("LastModified")
    return Details(int(root.get("Size") or 0), datetime.fromtimestamp(stamp) if stamp else None,
                   key if isinstance(key, bytes) else None)


def _unique(folder: Path, name: str) -> Path:
    name = name.replace("/", "-").strip(". ") or "unnamed"
    target, n = folder / name, 2
    stem, dot, ext = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
    while target.exists():
        target = folder / (f"{stem} ({n}).{ext}" if dot else f"{name} ({n})")
        n += 1
    return target


class BackupReader:
    def __init__(self, folder: Path, db: sqlite3.Connection, keys: dict[int, bytes] | None, info: dict,
                 saved: dict[str, AppMeta]):
        self.folder = folder
        self.encrypted = keys is not None
        self._db = db
        self._keys = keys
        self._lock = threading.Lock()
        self._info = info
        product = info.get("Product Type")
        self._device = "On My iPad" if isinstance(product, str) and product.startswith("iPad") else "On My iPhone"
        self._build(app_catalog(info, saved))

    def _build(self, apps: dict[str, AppMeta]):
        self._apps = apps
        self._root = Node("", True, children={})
        places: dict[str, tuple[tuple[str, ...], str | None]] = {}
        with self._lock:
            rows = self._db.execute("SELECT fileID, domain, relativePath, flags FROM Files").fetchall()
        for file_id, domain, relative, flags in rows:
            if flags not in (_FILE, _DIR):
                continue
            if domain not in places:
                places[domain] = _place(domain, apps)
                self._mark_app(*places[domain])
            inside = (p for p in (relative or "").split("/") if p not in ("", ".", ".."))
            parts = [*places[domain][0], *inside]
            node = self._root
            for part in parts[:-1]:
                node = node.children.setdefault(part, Node(part, True, children={}))
                if not node.is_dir:
                    break
            else:
                name = parts[-1]
                if flags == _FILE:
                    node.children.setdefault(name, Node(name, False, file_id))
                else:
                    node.children.setdefault(name, Node(name, True, children={}))
        domain, folder = _LOCAL_STORAGE
        storage = self.find((*places[domain][0], folder)) if domain in places else None
        if storage is not None and storage.is_dir:
            self._root.children[self._device] = Node(self._device, True, children=storage.children)

    def relabel(self, saved: dict[str, AppMeta]):
        """Rebuilds the tree with newly saved app names and icons."""
        self._build(app_catalog(self._info, saved))

    def _mark_app(self, parts: tuple[str, ...], bid: str | None):
        if bid:
            folder = self._root.children.setdefault("Apps", Node("Apps", True, children={}))
            folder.children.setdefault(parts[1], Node(parts[1], True, children={})).app = bid

    @classmethod
    def open(cls, folder: Path, password: str | None, saved: dict[str, AppMeta] | None = None) -> "BackupReader":
        folder = Path(folder)
        manifest = plistlib.loads((folder / "Manifest.plist").read_bytes())
        try:
            info = plistlib.loads((folder / "Info.plist").read_bytes())
        except (OSError, plistlib.InvalidFileException):
            info = {}
        keys = None
        if manifest.get("IsEncrypted"):
            if not password:
                raise PasswordNeeded
            keys = _unlock(manifest["BackupKeyBag"], password)
            decryptor = _decryptor(_unwrap(keys, manifest["ManifestKey"]))
            data = decryptor.update((folder / "Manifest.db").read_bytes()) + decryptor.finalize()
            db = sqlite3.connect(":memory:", check_same_thread=False)
            db.deserialize(data[:len(data) - data[-1]] if data and data[-1] <= 16 else data)
        else:
            db = sqlite3.connect(f"{(folder / 'Manifest.db').as_uri()}?mode=ro&immutable=1", uri=True,
                                 check_same_thread=False)
        return cls(folder, db, keys, info, saved or {})

    def close(self):
        with self._lock:
            self._db.close()

    def find(self, path: tuple[str, ...]) -> Node | None:
        node = self._root
        for part in path:
            node = (node.children or {}).get(part)
            if node is None:
                return None
        return node

    def listing(self, path: tuple[str, ...]) -> list[Node]:
        node = self.find(path)
        if node is None or not node.is_dir:
            return []
        if not path:
            return sorted(node.children.values(), key=lambda n: TOP_LEVEL.index(n.name))
        return sorted(node.children.values(), key=lambda n: (not n.is_dir, n.name.casefold()))

    def icon(self, node: Node) -> bytes | None:
        meta = self._apps.get(node.app) if node.app else None
        return meta.icon if meta else None

    def details(self, node: Node) -> Details:
        with self._lock:
            row = self._db.execute("SELECT file FROM Files WHERE fileID = ?", (node.file_id,)).fetchone()
        return _details(row[0]) if row and row[0] else Details(0, None, None)

    def source(self, node: Node) -> Path:
        return self.folder / node.file_id[:2] / node.file_id

    def _copy(self, node: Node, target: Path):
        details = self.details(node)
        with open(self.source(node), "rb") as src, open(target, "wb") as dst:
            if self._keys is None or details.key is None:
                while chunk := src.read(_CHUNK):
                    dst.write(chunk)
            else:
                decryptor = _decryptor(_unwrap(self._keys, details.key))
                unpadder = PKCS7(128).unpadder()
                while chunk := src.read(_CHUNK):
                    dst.write(unpadder.update(decryptor.update(chunk)))
                dst.write(unpadder.update(decryptor.finalize()) + unpadder.finalize())
            if details.size and dst.tell() > details.size:
                dst.truncate(details.size)
        if details.modified:
            stamp = details.modified.timestamp()
            os.utime(target, (stamp, stamp))

    def export(self, nodes: list[Node], dest: Path, on_item) -> ExportResult:
        """on_item(index, total, name) runs before each file; folders are recreated under dest."""
        jobs: list[tuple[Path, Node]] = []

        def walk(node: Node, folder: Path):
            if node.is_dir:
                target = _unique(folder, node.name)
                target.mkdir(parents=True)
                for child in node.children.values():
                    walk(child, target)
            else:
                jobs.append((folder, node))

        for node in nodes:
            walk(node, Path(dest))
        result = ExportResult()
        for index, (folder, node) in enumerate(jobs):
            on_item(index, len(jobs), node.name)
            target = _unique(folder, node.name)
            try:
                self._copy(node, target)
            except FileNotFoundError:
                target.unlink(missing_ok=True)
                result.missing += 1
                continue
            result.saved.append(target)
        return result
