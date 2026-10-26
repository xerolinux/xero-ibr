import hashlib
import os
import plistlib
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap
from cryptography.hazmat.primitives.padding import PKCS7

TOP_LEVEL = ("Camera Roll", "Home", "Media", "Apps", "App Groups", "App Extensions", "System")
_FIXED = {"CameraRollDomain": ("Camera Roll",), "HomeDomain": ("Home",), "MediaDomain": ("Media",)}
_PREFIXES = (("AppDomainGroup-", "App Groups"), ("AppDomainPlugin-", "App Extensions"), ("AppDomain-", "Apps"))
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


@dataclass(frozen=True)
class Details:
    size: int
    modified: datetime | None
    key: bytes | None


@dataclass
class ExportResult:
    saved: list[Path] = field(default_factory=list)
    missing: int = 0


def domain_folder(domain: str, names: dict[str, str]) -> tuple[str, ...]:
    for prefix, folder in _PREFIXES:
        if domain.startswith(prefix):
            ident = domain[len(prefix):]
            return folder, names.get(ident, ident)
    return _FIXED.get(domain, ("System", domain))


def app_names(info: dict) -> dict[str, str]:
    found = {}
    for bundle_id, app in (info.get("Applications") or {}).items():
        try:
            name = plistlib.loads(app["iTunesMetadata"]).get("itemName")
        except Exception:
            continue
        if isinstance(name, str) and name.strip():
            found[bundle_id] = name.strip().replace("/", "-")
    counts: dict[str, int] = {}
    for name in found.values():
        counts[name] = counts.get(name, 0) + 1
    return {bid: f"{name} ({bid})" if counts[name] > 1 else name for bid, name in found.items()}


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
    def __init__(self, folder: Path, db: sqlite3.Connection, keys: dict[int, bytes] | None, names: dict[str, str]):
        self.folder = folder
        self.encrypted = keys is not None
        self._db = db
        self._keys = keys
        self._lock = threading.Lock()
        self._root = Node("", True, children={})
        for file_id, domain, relative, flags in db.execute("SELECT fileID, domain, relativePath, flags FROM Files"):
            if flags not in (_FILE, _DIR):
                continue
            inside = (p for p in (relative or "").split("/") if p not in ("", ".", ".."))
            parts = [*domain_folder(domain, names), *inside]
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

    @classmethod
    def open(cls, folder: Path, password: str | None) -> "BackupReader":
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
        return cls(folder, db, keys, app_names(info))

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
