import hashlib
import os
import plistlib
import sqlite3
import struct
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap
from cryptography.hazmat.primitives.padding import PKCS7

PASSWORD = "secret"
MODIFIED = 1761400000


def _tlv(tag: bytes, value) -> bytes:
    if isinstance(value, int):
        value = struct.pack(">L", value)
    return tag + struct.pack(">L", len(value)) + value


def _encrypt(key: bytes, data: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b"\0" * 16)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _mbfile(size: int, key_blob: bytes | None) -> bytes:
    root = {"$class": plistlib.UID(3), "Size": size, "LastModified": MODIFIED, "ProtectionClass": 3}
    objects = ["$null", root, {"$classname": "MBFile"}]
    if key_blob is not None:
        root["EncryptionKey"] = plistlib.UID(3)
        objects = ["$null", root, {"$classname": "MBFile"}, {"NS.data": key_blob, "$class": plistlib.UID(2)}]
        root["$class"] = plistlib.UID(2)
    archive = {"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": plistlib.UID(1)},
               "$objects": objects}
    return plistlib.dumps(archive, fmt=plistlib.FMT_BINARY)


FILES = [
    ("CameraRollDomain", "Media", 2, None),
    ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.JPG", 1, b"jpeg bytes " * 50),
    ("HomeDomain", "Library/SMS/sms.db", 1, b"messages"),
    ("AppDomain-com.example.notes", "Documents/note.txt", 1, b"hello note"),
    ("AppDomainGroup-group.com.example", "shared.plist", 1, b"group"),
    ("KeychainDomain", "keychain-backup.plist", 1, b"keychain"),
    ("HomeDomain", "Library/link", 4, None),
]


def make_backup(folder: Path, encrypted: bool) -> Path:
    folder.mkdir(parents=True)
    class_key = os.urandom(32)
    passcode_key = hashlib.pbkdf2_hmac("sha1", hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), b"d" * 20, 3, 32),
                                       b"s" * 20, 2, 32)
    keybag = b"".join([
        _tlv(b"VERS", 4), _tlv(b"TYPE", 1), _tlv(b"UUID", b"k" * 16), _tlv(b"WRAP", 0),
        _tlv(b"SALT", b"s" * 20), _tlv(b"ITER", 2), _tlv(b"DPWT", 1), _tlv(b"DPIC", 3), _tlv(b"DPSL", b"d" * 20),
        _tlv(b"UUID", b"c" * 16), _tlv(b"CLAS", 3), _tlv(b"WRAP", 2), _tlv(b"KTYP", 0),
        _tlv(b"WPKY", aes_key_wrap(passcode_key, class_key)),
    ])

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, "
               "file BLOB)")
    for domain, relative, flags, content in FILES:
        file_id = hashlib.sha1(f"{domain}-{relative}".encode()).hexdigest()
        key_blob = None
        if content is not None:
            stored = content
            if encrypted:
                file_key = os.urandom(32)
                key_blob = struct.pack("<L", 3) + aes_key_wrap(class_key, file_key)
                stored = _encrypt(file_key, content)
            target = folder / file_id[:2] / file_id
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(stored)
        db.execute("INSERT INTO Files VALUES (?, ?, ?, ?, ?)",
                   (file_id, domain, relative, flags, _mbfile(len(content or b""), key_blob)))
    db.commit()
    data = db.serialize()

    manifest = {"IsEncrypted": encrypted, "Version": "10.0"}
    if encrypted:
        manifest_key = os.urandom(32)
        manifest["BackupKeyBag"] = keybag
        manifest["ManifestKey"] = struct.pack("<L", 3) + aes_key_wrap(class_key, manifest_key)
        data = _encrypt(manifest_key, data)
    (folder / "Manifest.db").write_bytes(data)
    (folder / "Manifest.plist").write_bytes(plistlib.dumps(manifest))
    info = {"Device Name": "Test iPhone", "Last Backup Date": datetime(2026, 10, 25),
            "Applications": {"com.example.notes": {"iTunesMetadata": plistlib.dumps({"itemName": "Notes Plus"})}}}
    (folder / "Info.plist").write_bytes(plistlib.dumps(info))
    return folder
