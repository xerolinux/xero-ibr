"""Run iBR with fake devices and backups, optionally saving screenshots of each state.

Usage: python tools/demo.py [--shots OUTPUT_DIR] [--theme dark|light]
"""
import argparse
import io
import math
import os
import plistlib
import shlex
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

args = argparse.ArgumentParser()
args.add_argument("--shots")
args.add_argument("--theme", default="dark")
args.add_argument("--scene", default="phone",
                  choices=["phone", "ipad", "pro17", "older-ios", "old", "trust", "empty", "recovery", "dfu",
                           "recovery-locked"])
opts = args.parse_args()

sandbox = Path(tempfile.mkdtemp(prefix="ibr-demo-"))
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(sandbox / var.lower())

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ibr.app import Application  # noqa: E402
from ibr.core.deviceinfo import parse_device_info  # noqa: E402
from ibr.core.settings import Settings  # noqa: E402
from ibr.core.snapshots import create_snapshot  # noqa: E402
from ibr.services.devices import Device, DeviceMonitor  # noqa: E402

PHONE = "00008140-001C2D3E4F506172"
IPAD = "00008112-000A1B2C3D4E5F60"
OLD = "00008030-0012AB34CD56EF78"


def make_backup(root: Path, udid: str, name: str, product: str, version: str, when: datetime, size: int):
    folder = root / udid
    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*.plist"):
        path.unlink()
    (folder / "Info.plist").write_bytes(plistlib.dumps({
        "Device Name": name, "Product Type": product, "Product Version": version,
        "Last Backup Date": when.astimezone(timezone.utc).replace(tzinfo=None)}))
    (folder / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))
    (folder / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": "finished"}))
    blobs = folder / "ab"
    blobs.mkdir(exist_ok=True)
    for old in blobs.iterdir():
        old.unlink()
    blob = blobs / f"blob-{when:%d}"
    with open(blob, "wb") as handle:
        handle.truncate(size)


DEMO_IPSWS = ("iPhone17,1_26.1_23B85_Restore.ipsw", "iPhone17,1_26.0.1_23A355_Restore.ipsw",
              "iPad16,5_iPad16,6_26.1_23B85_Restore.ipsw")


def seed_firmware(settings):
    """Sparse stand-ins for downloaded iPSWs, in a library folder inside the sandbox."""
    firmware = sandbox / "Firmware"
    firmware.mkdir(exist_ok=True)
    for name in DEMO_IPSWS:
        with open(firmware / name, "wb") as handle:
            handle.truncate(9_100_000_000)
    settings.firmware_dir = str(firmware)
    settings.save()


def seed_backups(root: Path):
    now = datetime.now()
    for days, size in ((23, 39_900_000_000), (9, 40_800_000_000), (2, 41_200_000_000)):
        when = now - timedelta(days=days)
        make_backup(root, PHONE, "My iPhone", "iPhone17,1", "26.0.1", when, size)
        create_snapshot(root, PHONE, when.strftime("%Y%m%d-%H%M%S"))
    for days in (40, 12):
        when = now - timedelta(days=days)
        make_backup(root, IPAD, "Studio iPad", "iPad16,5", "26.0", when, 12_000_000_000)
        create_snapshot(root, IPAD, when.strftime("%Y%m%d-%H%M%S"))
    make_backup(root, OLD, "Old iPhone 11", "iPhone12,1", "18.6.2", now - timedelta(days=120), 8_000_000_000)
    make_browsable(root / OLD)
    from ibr.core.app_catalog import AppMeta, catalog_file, save_merged
    save_merged(catalog_file(PHONE), {bid: AppMeta(name, demo_icon(name, colour)) for bid, name, colour in (
        ("com.readdle.Documents", "Documents", "#3d7bf7"), ("org.videolan.vlc-ios", "VLC", "#f28a1e"),
        ("com.firecore.infuse", "Infuse", "#e8562a"))})


BROWSABLE = [
    ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.PNG"),
    ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0002.PNG"),
    ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0003.PNG"),
    ("HomeDomain", "Library/SMS/sms.db"),
    ("HomeDomain", "Library/Notes/notes.sqlite"),
    ("MediaDomain", "Media/Recordings/Voice Memo.m4a"),
    ("AppDomain-com.apple.mobilesafari", "Library/Safari/Bookmarks.db"),
    ("AppDomainGroup-group.com.apple.notes", "NoteStore.sqlite"),
    ("AppDomain-org.videolan.vlc-ios", "Documents/Lecture.txt"),
    ("AppDomainGroup-group.org.videolan.vlc-ios", "Library/Preferences/settings.plist"),
    ("AppDomain-net.whatsapp.WhatsApp", "Documents/ChatStorage.sqlite"),
    ("AppDomainGroup-group.net.whatsapp.WhatsApp.shared", "Message/Media/photo.txt"),
    ("AppDomainPlugin-net.whatsapp.WhatsApp.ShareExtension", "Library/Preferences/share.plist"),
    ("AppDomain-com.8bit.bitwarden", "Library/Preferences/settings.plist"),
    ("AppDomainPlugin-com.8bit.bitwarden.autofill", "Library/Preferences/autofill.plist"),
    ("AppDomain-com.spotify.client", "Library/Preferences/com.spotify.client.plist"),
    ("AppDomain-com.apple.AAUIViewService", "Library/Preferences/state.plist"),
    ("AppDomainGroup-group.com.apple.FileProvider.LocalStorage", "File Provider Storage/Downloads/Invoice.pdf"),
    ("AppDomainGroup-group.com.apple.FileProvider.LocalStorage", "File Provider Storage/Scans/Receipt.pdf"),
    ("KeychainDomain", "keychain-backup.plist"),
    ("WirelessDomain", "Library/Preferences/com.apple.wifi.plist"),
]


DEMO_APPS = [("org.videolan.vlc-ios", "VLC media player", "#f28a1e"), ("net.whatsapp.WhatsApp", "WhatsApp", "#25d366"),
             ("com.8bit.bitwarden", "Bitwarden Password Manager", "#175ddc"),
             ("com.spotify.client", "Spotify: Music and Podcasts", "#1db954")]


def demo_icon(name: str, colour: str) -> bytes:
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 128, 128)
    cr = cairo.Context(surface)
    red, green, blue = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    cr.new_sub_path()
    for x, y, start in ((100, 28, -0.5), (100, 100, 0), (28, 100, 0.5), (28, 28, 1)):
        cr.arc(x, y, 28, start * math.pi, (start + 0.5) * math.pi)
    cr.close_path()
    cr.set_source_rgb(red, green, blue)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(64)
    extents = cr.text_extents(name[0])
    cr.move_to(64 - extents.width / 2 - extents.x_bearing, 64 - extents.height / 2 - extents.y_bearing)
    cr.show_text(name[0])
    out = io.BytesIO()
    surface.write_to_png(out)
    return out.getvalue()


def make_browsable(folder: Path):
    """Gives the old iPhone's backup a real unencrypted manifest so the backup browser has content."""
    import hashlib
    import sqlite3
    (folder / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    info = plistlib.loads((folder / "Info.plist").read_bytes())
    info["Applications"] = {bid: {"iTunesMetadata": plistlib.dumps({"itemName": name}),
                                  "PlaceholderIcon": demo_icon(name, colour)}
                            for bid, name, colour in DEMO_APPS}
    (folder / "Info.plist").write_bytes(plistlib.dumps(info))
    from ibr.core.app_catalog import AppMeta, catalog_file, save_merged
    save_merged(catalog_file(folder.name), {
        "com.apple.mobilenotes": AppMeta("Notes", demo_icon("Notes", "#f5c02c")),
        "com.apple.mobilesafari": AppMeta("Safari", demo_icon("Safari", "#1f8cf0"))})
    db = sqlite3.connect(folder / "Manifest.db")
    db.execute("DROP TABLE IF EXISTS Files")
    db.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    stamp = int(datetime(2026, 6, 14, 9, 30).timestamp())
    for domain, relative in BROWSABLE:
        file_id = hashlib.sha1(f"{domain}-{relative}".encode()).hexdigest()
        target = folder / file_id[:2] / file_id
        target.parent.mkdir(exist_ok=True)
        if relative.endswith(".PNG"):
            demo_photo(target)
        else:
            target.write_text("iBR demo file from a simulated backup.\n")
        root = {"Size": target.stat().st_size, "LastModified": stamp, "$class": plistlib.UID(2)}
        blob = plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": plistlib.UID(1)},
                               "$objects": ["$null", root, {"$classname": "MBFile"}]}, fmt=plistlib.FMT_BINARY)
        db.execute("INSERT INTO Files VALUES (?, ?, ?, 1, ?)", (file_id, domain, relative, blob))
    db.commit()
    db.close()


def fake_info(udid, name, product, version, klass, total, available, battery, charging):
    return parse_device_info(
        plistlib.dumps({"UniqueDeviceID": udid, "DeviceName": name, "ProductType": product,
                        "ProductVersion": version, "DeviceClass": klass, "SerialNumber": "F2LXK9Q7PQ7",
                        "ModelNumber": "MYNF3", "RegionInfo": "B/A"}),
        plistlib.dumps({"BatteryCurrentCapacity": battery, "BatteryIsCharging": charging}),
        plistlib.dumps({"TotalDiskCapacity": total, "TotalDataAvailable": available}),
        plistlib.dumps({"WillEncrypt": True}),
    )


class DemoMonitor(DeviceMonitor):
    def __init__(self):
        super().__init__()
        self.scene = "empty"

    def exit_recovery(self, device, callback):
        def back():
            self.scene = "phone"
            self.scan()
            return False
        GLib.timeout_add(400, lambda: callback(True, "") and False)
        GLib.timeout_add(3000, back)

    def set_polling(self, enabled):
        pass

    def scan(self, refresh=True, quiet=False):
        from ibr.services.devices import RecoveryDevice
        self.usbmuxd_ok = self.scene != "empty"
        self.devices.clear()
        self.recovery.clear()
        if self.scene in ("recovery", "dfu", "recovery-locked"):
            mode = "DFU" if self.scene == "dfu" else "Recovery"
            locked = self.scene == "recovery-locked"
            device = RecoveryDevice("0x1A2B3C4D5E6F70", mode, "0x1A2B3C4D5E6F70", None if locked else "iPhone17,1",
                                    None if locked else "iPhone 16 Pro", True,
                                    "ERROR: Unable to connect to device" if locked else "")
            self.recovery[device.key] = device
        if self.scene in ("phone", "trust"):
            device = Device(PHONE, "trust" if self.scene == "trust" else "ready")
            if self.scene == "trust":
                device.message = "Tap Trust on your device and enter its passcode."
            else:
                device.info = fake_info(PHONE, "My iPhone", "iPhone17,1", "26.0.1", "iPhone",
                                        256_000_000_000, 108_000_000_000, 87, True)
            self.devices[PHONE] = device
        elif self.scene == "ipad":
            device = Device(IPAD, "ready")
            device.info = fake_info(IPAD, "Studio iPad", "iPad16,5", "26.0", "iPad",
                                    1_000_000_000_000, 388_000_000_000, 93, False)
            self.devices[IPAD] = device
        elif self.scene == "older-ios":
            device = Device(PHONE, "ready")
            device.info = fake_info(PHONE, "My iPhone", "iPhone17,1", "18.6", "iPhone",
                                    256_000_000_000, 108_000_000_000, 87, True)
            self.devices[PHONE] = device
        elif self.scene == "pro17":
            device = Device("PRO17", "ready")
            device.info = fake_info("PRO17", "Work iPhone", "iPhone18,1", "26.0.1", "iPhone",
                                    512_000_000_000, 300_000_000_000, 64, False)
            self.devices["PRO17"] = device
        elif self.scene == "old":
            device = Device("OLDIOS", "ready")
            device.info = fake_info("OLDIOS", "Kitchen iPhone", "iPhone10,1", "14.8.1", "iPhone",
                                    64_000_000_000, 20_000_000_000, 58, False)
            self.devices["OLDIOS"] = device
        self.emit("changed")


DEMO_SONGS = [("Morning Light", 523.25), ("Harbour", 440.0), ("Desert Road", 392.0), ("Static Bloom", 349.23)]


class FakeAfc:
    TREE = {
        "/": [("DCIM", True, 0), ("Downloads", True, 0), ("Books", True, 0), ("Recordings", True, 0)],
        "/DCIM": [("100APPLE", True, 0), ("101APPLE", True, 0)],
        "/DCIM/100APPLE": [(f"IMG_{n:04d}.HEIC", False, 2_400_000 + n * 1000) for n in range(1, 9)]
        + [("IMG_0009.MOV", False, 84_000_000)],
    }

    APP_TREE = {"/Documents": [("Movies", True, 0), ("Music", True, 0), ("Holiday.mkv", False, 1_900_000_000),
                               ("Lecture.mp4", False, 620_000_000)],
                "/Documents/Music": [(f"{title}.m4a", False, 7_400_000) for title, _ in DEMO_SONGS]}

    def __init__(self, udid, app_id=None):
        self.app_id = app_id
        self.tree = self.APP_TREE if app_id else self.TREE

    @staticmethod
    def _later(callback, *args, delay=250):
        GLib.timeout_add(delay, lambda: callback(*args) and False)

    def _split(self, path):
        folder, _, name = path.rpartition("/")
        return folder or "/", name

    def fetch(self, remote, target):
        from ibr.core.afc import media_kind
        if remote.startswith("/PhotoData/Thumbnails/"):
            demo_thumb(Path(target), remote.split("/")[-2])
            return True
        if media_kind(remote, False) == "audio":
            demo_song(Path(target))
            return Path(target).exists()
        return False

    def list(self, path, callback):
        from ibr.core.afc import RemoteEntry
        when = datetime(2026, 10, 20, 14, 5)
        rows = sorted(self.tree.get(path, []), key=lambda r: (not r[1], r[0].lower()))
        self._later(callback, [RemoteEntry(n, d, s, when) for n, d, s in rows], None, delay=150)

    def mkdir(self, path, callback):
        folder, name = self._split(path)
        self.tree.setdefault(folder, []).append((name, True, 0))
        self.tree[path] = []
        self._later(callback, "", None)

    def remove(self, paths, callback):
        for path in paths:
            folder, name = self._split(path)
            self.tree[folder] = [row for row in self.tree.get(folder, []) if row[0] != name]
        self._later(callback, "", None)

    def download(self, remote, local_dir, callback):
        from ibr.core.afc import media_kind
        target = Path(local_dir) / self._split(remote)[1]
        if media_kind(target.name, False) == "image":
            demo_photo(target)
        elif media_kind(target.name, False) == "audio":
            demo_song(target)
        else:
            target.write_text("iBR demo file: copied from the simulated device.\n")
        self._later(callback, target, None, delay=600)

    def upload(self, local, remote_dir, callback):
        local = Path(local)
        size = local.stat().st_size if local.is_file() else 0
        self.tree.setdefault(remote_dir, []).append((local.name, local.is_dir(), size))
        self._later(callback, "", None, delay=600)


def demo_song(path: Path):
    """A short tone tagged like a real song, with cover art, made with ffmpeg."""
    import subprocess
    import tempfile
    title = path.stem
    pitch = dict(DEMO_SONGS).get(title, 440.0)
    with tempfile.TemporaryDirectory() as work:
        cover = Path(work) / "cover.png"
        demo_thumb(cover, title)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", f"sine=frequency={pitch}:duration=20", "-i", str(cover), "-map", "0:a", "-map", "1",
                        "-c:a", "aac", "-c:v", "png",
                        "-disposition:v", "attached_pic", "-metadata", f"title={title}",
                        "-metadata", "artist=The Long Hours", "-metadata", "album=Night Drives", str(path)],
                       check=False)


def demo_thumb(path: Path, name: str):
    """A small made-up photo whose colours depend on the file name."""
    import cairo
    import colorsys
    hue = (sum(map(ord, name)) * 37 % 360) / 360
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 256, 192)
    cr = cairo.Context(surface)
    sky = cairo.LinearGradient(0, 0, 0, 192)
    sky.add_color_stop_rgb(0, *colorsys.hls_to_rgb(hue, 0.35, 0.55))
    sky.add_color_stop_rgb(1, *colorsys.hls_to_rgb((hue + 0.1) % 1, 0.7, 0.7))
    cr.set_source(sky)
    cr.paint()
    cr.set_source_rgb(*colorsys.hls_to_rgb((hue + 0.5) % 1, 0.25, 0.4))
    cr.move_to(0, 192)
    cr.line_to(90, 110)
    cr.line_to(150, 150)
    cr.line_to(210, 90)
    cr.line_to(256, 140)
    cr.line_to(256, 192)
    cr.fill()
    surface.write_to_png(str(path))


def demo_photo(path: Path):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 1600, 1200)
    cr = cairo.Context(surface)
    sky = cairo.LinearGradient(0, 0, 0, 1200)
    sky.add_color_stop_rgb(0, 0.27, 0.27, 0.72)
    sky.add_color_stop_rgb(0.6, 0.86, 0.52, 0.42)
    sky.add_color_stop_rgb(1, 0.98, 0.78, 0.48)
    cr.set_source(sky)
    cr.paint()
    cr.arc(1100, 520, 140, 0, 2 * math.pi)
    cr.set_source_rgb(1, 0.92, 0.7)
    cr.fill()
    cr.move_to(0, 1200)
    for x, y in ((0, 820), (300, 640), (620, 860), (900, 600), (1250, 880), (1600, 700), (1600, 1200)):
        cr.line_to(x, y)
    cr.set_source_rgb(0.13, 0.12, 0.2)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.set_font_size(48)
    cr.move_to(60, 1140)
    cr.show_text(f"{path.name} (simulated photo)")
    surface.write_to_png(str(path))


def fake_apps(udid):
    from ibr.core.afc import SharingApp
    return [SharingApp("com.readdle.Documents", "Documents"), SharingApp("org.videolan.vlc-ios", "VLC"),
            SharingApp("com.firecore.infuse", "Infuse")]


def _script(lines: list[tuple[str, float]]) -> tuple[list[str], dict]:
    body = "; ".join(f"printf '%s' {shlex.quote(text)}; sleep {pause}" for text, pause in lines)
    return ["sh", "-c", body], {}


def fake_backup_cmd(udid, root, full=False):
    lines = [("Starting backup...\n", 0.6), ("Requesting backup from device...\n", 0.8), ("Receiving files\n", 0.3)]
    total = 41.8
    for step in range(1, 41):
        done = total * step / 40
        lines.append((f"\r[{'=' * (step // 2)}] {step * 100 // 40:3d}% ({done:.1f} GB/{total} GB)     ", 0.2))
        if step % 4 == 0:
            lines.append((f"\r[==] {step * 100 // 40:3d}% Finished\n", 0.05))
    lines.append(("Received 31880 files from device.\nBackup Successful.\n", 0))
    return _script(lines)


def fake_restore_cmd(udid, root, options):
    lines = [("Starting Restore...\n", 1.0)]
    for step in range(1, 21):
        lines.append((f"Sending 'Snapshot/{step:02d}.db' (850.0 MB)\n", 0.3))
        lines.append((f"\r[==] {step * 5:3d}% Finished\n", 0.05))
    lines.append(("Restore Successful.\n", 0))
    return _script(lines)


def fake_encryption_cmd(udid, enable, password):
    word = "enabled" if enable else "disabled"
    return _script([("Please confirm by entering the passcode on the device.\n", 2.0),
                    (f"Backup encryption has been {word} successfully.\n", 0)])


def fake_changepw_cmd(udid, old, new):
    return _script([("Please confirm changing the backup password by entering the passcode on the device.\n", 2.0),
                    ("Backup encryption password has been changed successfully.\n", 0)])


def fake_firmware_cmd(udid, erase, ipsw, cache, ecid=None):
    output = {
        0: ["Found device in Normal mode", "Identified device as iPhone17,1",
            "Product version: 26.1", "Product build: 23B85 Major: 23",
            "Variant: Customer Upgrade Install (IPSW)", "All required components found in IPSW"],
        1: ["Getting ApNonce in normal mode... 32 bytes", "Sending TSS request to gs.apple.com... OK",
            "Received SHSH blobs", "Entering recovery mode...", "Sending iBEC (1192 bytes)... DONE",
            "Waiting for device to reconnect in Restore mode... OK", "Sending RestoreRamDisk... DONE"],
        2: ["About to send RootFS...", "Sending RootFS (5.82 GB)..."],
        3: ["Verifying restore...", "Checking filesystems (15)..."],
        4: ["Updating SE Firmware", "Updating Baseband", "Flashing firmware components..."],
    }
    lines = []
    for step, pause in ((0, 0.15), (1, 0.15), (2, 0.08), (3, 0.08), (4, 0.08)):
        lines += [(f"{text}\n", 0.12) for text in output[step]]
        lines += [(f"progress: {step} {n / 20:.6f}\n", pause) for n in range(1, 21)]
    lines.append(("Status: Restore Finished\nDONE\n", 0))
    return _script(lines)


def fake_update_install(info, progress, done):
    steps = iter(range(1, 21))

    def tick():
        step = next(steps, None)
        if step is None:
            done(None)
            return False
        progress(step / 20)
        return True

    GLib.timeout_add(120, tick)


def demo_relaunch():
    import subprocess
    subprocess.Popen(["/bin/sh", "-c", 'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; exec "$2" "$3" --scene phone',
                      "demo", str(os.getpid()), sys.executable, str(Path(__file__).resolve())],
                     start_new_session=True)


def install_simulation():
    import ibr.ui.files_view as files_view
    import ibr.ui.firmware_dialog as firmware_dialog
    import ibr.ui.restore_dialog as restore_dialog
    import ibr.ui.window as window

    window.backup_cmd = fake_backup_cmd
    window.encryption_cmd = fake_encryption_cmd
    window.changepw_cmd = fake_changepw_cmd
    restore_dialog.restore_cmd = fake_restore_cmd
    firmware_dialog.firmware_cmd = fake_firmware_cmd
    files_view.Afc = FakeAfc
    files_view.list_sharing_apps = fake_apps
    files_view.refresh_app_catalog = lambda udid: False
    firmware_dialog.check_tool = lambda callback: GLib.idle_add(lambda: callback("ok") and False)
    from ibr.core.update import UpdateInfo
    from ibr.services import updater
    updater.check = lambda callback: GLib.idle_add(lambda: callback(
        UpdateInfo("0.2.0", "https://example.invalid/iBR.AppImage", "0" * 64)) and False)
    updater.install = fake_update_install
    updater.relaunch_after_exit = demo_relaunch


def screenshot(window: Gtk.Window, path: Path):
    width, height = window.get_width(), window.get_height()
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        return
    texture = window.get_renderer().render_texture(node, None)
    texture.save_to_png(str(path))
    print("saved", path)


def main():
    settings = Settings.load()
    settings.theme = opts.theme
    settings.save()
    seed_backups(Path(settings.backup_dir))
    seed_firmware(settings)
    print(f"Demo firmware files: {settings.firmware_dir}", flush=True)
    install_simulation()
    monitor = DemoMonitor()
    app = Application(monitor)
    out = Path(opts.shots) if opts.shots else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    def progress_scene(win):
        monitor.scene = "phone"
        monitor.scan()
        win._busy_udid = PHONE
        win.begin_operation("demo")
        win.device_view.set_busy("backup")
        feed = "Starting backup...\nReceiving files\n\r[====] 40% (25.9 GB/41.8 GB)     \r[=====] 62% Finished\n"
        from ibr.core.progress import ProgressParser
        for event in ProgressParser().feed(feed):
            win._on_backup_event(None, event)

    def end_progress(win):
        win.device_view.set_idle()
        win._busy_udid = None
        win.end_operation()

    def open_dialog(win, factory):
        dialog = factory(win)
        dialog.present()
        win._dialog = dialog

    def close_dialog(win):
        if getattr(win, "_dialog", None):
            win._dialog.destroy()
            win._dialog = None

    def restore(win):
        from ibr.ui.restore_dialog import RestoreDialog
        open_dialog(win, lambda w: RestoreDialog(w, w.current_device_info(), w.backups, None))

    def settings_window(win):
        from ibr.ui.settings_window import SettingsWindow
        open_dialog(win, SettingsWindow)

    def encrypt(win):
        from ibr.ui.password_dialog import PasswordDialog
        open_dialog(win, lambda w: PasswordDialog(w, "Turn on encryption", "Choose a password for encrypted "
                                                  "backups. You need it to restore.", "new", lambda r: None,
                                                  remember=True))

    def about(win):
        from ibr.ui.about_window import AboutWindow
        open_dialog(win, AboutWindow)

    def manage(win):
        from ibr.ui.backups_window import BackupsWindow
        open_dialog(win, lambda w: BackupsWindow(w, PHONE))

    def files(win, path="/DCIM/100APPLE"):
        scene("phone")(win)
        win.open_files()
        GLib.timeout_add(300, lambda: win.files_view.open_path(path) and False)

    def browse(win, udid):
        win.open_backup(next(e for e in win.backups if e.udid == udid))

    def software(win):
        import ibr.ui.firmware_dialog as firmware_dialog
        from ibr.core.firmware import FirmwareTarget
        scene("older-ios")(win)
        open_dialog(win, lambda w: firmware_dialog.FirmwareDialog(
            w, FirmwareTarget.from_device(w.current_device_info())))

    def scene(name):
        def apply(win):
            monitor.scene = name
            monitor.scan()
        return apply

    steps = [
        ("01-scanning", scene("empty"), None),
        ("02-trust", scene("trust"), None),
        ("03-connected", scene("phone"), None),
        ("04-progress", progress_scene, None),
        ("05-ipad", lambda w: (end_progress(w), scene("ipad")(w)), None),
        ("06-unsupported", scene("old"), None),
        ("07-restore", lambda w: (scene("phone")(w), restore(w)), "dialog"),
        ("08-manage", lambda w: (close_dialog(w), manage(w)), "dialog"),
        ("09-settings", lambda w: (close_dialog(w), settings_window(w)), "dialog"),
        ("10-about", lambda w: (close_dialog(w), about(w)), "dialog"),
        ("11-encrypt", lambda w: (close_dialog(w), encrypt(w)), "dialog"),
        ("12-restore-older-ios", lambda w: (close_dialog(w), scene("older-ios")(w), restore(w)), "dialog"),
        ("12b-not-restorable", lambda w: None, "message"),
        ("13-iphone17pro", lambda w: (close_dialog(w), scene("pro17")(w)), None),
        ("14-files", lambda w: files(w), None),
        ("15-software", lambda w: (w.close_files(), software(w)), "dialog"),
        ("15b-recovery", lambda w: (close_dialog(w), scene("recovery")(w)), None),
        ("15c-recovery-locked", scene("recovery-locked"), None),
        ("15d-dfu", scene("dfu"), None),
        ("16-preview", lambda w: (close_dialog(w), files(w)), None),
        ("17-preview-open", lambda w: w.files_view._preview(w.files_view._store.get_item(0)), "preview"),
        ("18-backup-browse", lambda w: (w.close_files(), browse(w, OLD)), None),
        ("19-backup-photos", lambda w: w.backup_view.open_path(("Camera Roll", "Media", "DCIM", "100APPLE")), None),
        ("20-backup-apps", lambda w: w.backup_view.open_path(("Apps",)), None),
        ("20b-backup-app", lambda w: w.backup_view.open_path(("Apps", "WhatsApp")), None),
        ("21-backup-locked", lambda w: browse(w, PHONE), None),
    ]

    def run_steps(index=0):
        win = app.window
        if index >= len(steps):
            if out:
                app.quit()
            return False
        name, action, target = steps[index]
        action(win)

        def shoot():
            if out:
                if target == "preview":
                    from ibr.ui.preview_dialog import PreviewDialog
                    shown = [t for t in Gtk.Window.list_toplevels() if isinstance(t, PreviewDialog)]
                    if shown:
                        screenshot(shown[-1], out / f"{name}.png")
                        shown[-1].destroy()
                elif target == "message":
                    from ibr.ui.dialog import MessageDialog
                    shown = [t for t in Gtk.Window.list_toplevels() if isinstance(t, MessageDialog)]
                    if shown:
                        screenshot(shown[-1], out / f"{name}.png")
                        shown[-1].destroy()
                else:
                    screenshot(win._dialog if target == "dialog" else win, out / f"{name}.png")
            GLib.timeout_add(300, run_steps, index + 1)
            return False

        GLib.timeout_add(2500, shoot)
        return False

    def activated(_app):
        GLib.idle_add(lambda: app.window.sidebar.set_location(str(Path.home() / ".local/share/ibr/backups")) and False)
        if out:
            GLib.timeout_add(1200, run_steps)
        else:
            monitor.scene = opts.scene
            GLib.timeout_add(500, lambda: monitor.scan() and False)

    app.connect("activate", activated)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
