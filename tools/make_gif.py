"""Records an animated GIF tour of iBR using the demo's simulated devices.

Usage: python tools/make_gif.py docs/media/ibr-demo.gif
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUTPUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/media/ibr-demo.gif").resolve()
sys.argv = [sys.argv[0]]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo  # noqa: E402
from gi.repository import Gio, GLib, Gtk  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from ibr.app import Application  # noqa: E402
from ibr.core.settings import Settings  # noqa: E402

FRAMES = Path(tempfile.mkdtemp(prefix="ibr-gif-"))
SIZE = (1240, 760)


def grab(window: Gtk.Window) -> Image.Image:
    path = FRAMES / "grab.png"
    demo.screenshot(window, path)
    return Image.open(path).convert("RGB")


def composite(base: Image.Image, dialog: Image.Image) -> Image.Image:
    frame = Image.blend(base, Image.new("RGB", base.size, (10, 10, 14)), 0.55)
    scale = min(1.0, base.width * 0.86 / dialog.width, base.height * 0.9 / dialog.height)
    dialog = dialog.resize((int(dialog.width * scale), int(dialog.height * scale)), Image.LANCZOS)
    x, y = (base.width - dialog.width) // 2, (base.height - dialog.height) // 2
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (x + 6, y + 12, x + dialog.width + 6, y + dialog.height + 12))
    frame = Image.alpha_composite(frame.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14))).convert("RGB")
    frame.paste(dialog, (x, y))
    return frame


def fit(image: Image.Image) -> Image.Image:
    if image.size == SIZE:
        return image
    canvas = Image.new("RGB", SIZE, (52, 52, 59))
    image.thumbnail(SIZE, Image.LANCZOS)
    canvas.paste(image, ((SIZE[0] - image.width) // 2, (SIZE[1] - image.height) // 2))
    return canvas


def main():
    settings = Settings.load()
    settings.theme = "dark"
    settings.save()
    demo.seed_backups(Path(settings.backup_dir))
    demo.seed_firmware(settings)
    demo.install_simulation()
    monitor = demo.DemoMonitor()
    app = Application(monitor)
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    from ibr.ui import audio_player
    play = audio_player.AudioPlayer._start

    def muted_start(player, path, turn):
        play(player, path, turn)
        if player._stream:
            player._stream.set_muted(True)

    audio_player.AudioPlayer._start = muted_start
    frames: list[tuple[Path, float]] = []

    def save(image: Image.Image, seconds: float):
        path = FRAMES / f"f{len(frames):03d}.png"
        fit(image).save(path)
        frames.append((path, seconds))

    def scene(name):
        monitor.scene = name
        monitor.scan()

    def window_frame(seconds):
        return lambda win: save(grab(win), seconds)

    def dialog_frame(kind, seconds):
        def take(win):
            shown = [t for t in Gtk.Window.list_toplevels() if isinstance(t, kind) and t.get_visible()]
            if shown:
                save(composite(grab(win), grab(shown[-1])), seconds)
                shown[-1].destroy()
        return take

    def preview_photo(win):
        win.files_view._preview(win.files_view._store.get_item(0))

    def play_song(win):
        win.files_view._preview(win.files_view._store.get_item(0))

    def open_vlc(win):
        view = win.files_view
        next(b for b in view._app_buttons() if b.app and b.app.name == "VLC").emit("clicked")

    def firmware(win):
        from ibr.core.firmware import FirmwareTarget
        FirmwareDialog(win, FirmwareTarget.from_device(win.current_device_info())).present()

    def start_download(win):
        shown = [t for t in Gtk.Window.list_toplevels() if isinstance(t, FirmwareDialog) and t.get_visible()]
        if shown:
            shown[-1]._download_selected()

    def keep_frame(kind, seconds):
        def take(win):
            shown = [t for t in Gtk.Window.list_toplevels() if isinstance(t, kind) and t.get_visible()]
            if shown:
                save(composite(grab(win), grab(shown[-1])), seconds)
        return take

    def settings_window(win):
        from ibr.ui.settings_window import SettingsWindow
        dialog = SettingsWindow(win)
        dialog.present()
        GLib.timeout_add(300, lambda: dialog.get_child().get_vadjustment().set_value(330) and False)

    def browse(win, udid):
        win.close_files()
        win.open_backup(next(e for e in win.backups if e.udid == udid))

    import ibr.ui.firmware_dialog as firmware_dialog
    from ibr.ui.firmware_dialog import FirmwareDialog
    from ibr.ui.preview_dialog import PreviewDialog
    from ibr.ui.settings_window import SettingsWindow

    def fake_download(url, target, sha256, progress, cancelled):
        total = 9_100_000_000
        for step in range(1, 61):
            if cancelled():
                return "Cancelled"
            time.sleep(0.08)
            progress(step * total // 60, total)
        with open(target, "wb") as handle:
            handle.truncate(total)
        return None

    firmware_dialog.download_ipsw = fake_download

    # (action before waiting, wait in ms, capture)
    script = [
        (lambda w: (w.set_default_size(*SIZE), scene("empty")), 1500, window_frame(1.8)),
        (lambda w: scene("trust"), 1200, window_frame(1.4)),
        (lambda w: scene("phone"), 1500, window_frame(2.0)),
        (lambda w: w.start_backup(demo.PHONE), 900, window_frame(0.5)),
        *[(lambda w: None, 650, window_frame(0.4)) for _ in range(16)],
        (lambda w: None, 2600, window_frame(1.8)),
        (lambda w: (w.open_files(), GLib.timeout_add(300, lambda: w.files_view.open_path("/DCIM/100APPLE")
                                                       and False)), 1600, window_frame(1.8)),
        (preview_photo, 1600, dialog_frame(PreviewDialog, 2.0)),
        (open_vlc, 1200, window_frame(1.2)),
        (lambda w: w.files_view.open_path("/Documents/Music"), 5000, window_frame(1.8)),
        (play_song, 6000, dialog_frame(PreviewDialog, 2.4)),
        (lambda w: browse(w, demo.OLD), 1500, window_frame(1.8)),
        (lambda w: w.backup_view.open_path(("Camera Roll", "Media", "DCIM", "100APPLE")), 900, window_frame(1.8)),
        (lambda w: w.backup_view.open_path(("Apps",)), 900, window_frame(1.6)),
        (lambda w: w.backup_view.open_path(("Apps", "WhatsApp", "Shared")), 900, window_frame(1.8)),
        (lambda w: w.backup_view.tree._search.set_text("vl"), 900, window_frame(1.6)),
        (lambda w: (w.backup_view.tree._search.set_text(""), w.backup_view.open_path(("On My iPhone",))), 900,
         window_frame(1.6)),
        (lambda w: browse(w, demo.PHONE), 900, window_frame(1.8)),
        (lambda w: (w.close_backup(), scene("older-ios")), 1200, window_frame(1.4)),
        (firmware, 7000, keep_frame(FirmwareDialog, 2.2)),
        (start_download, 2500, keep_frame(FirmwareDialog, 1.2)),
        (lambda w: None, 2500, dialog_frame(FirmwareDialog, 1.6)),
        (lambda w: (scene("phone"), settings_window(w)), 1500, dialog_frame(SettingsWindow, 2.2)),
        (lambda w: scene("older-ios"), 1200, lambda w: None),
        (lambda w: scene("recovery"), 1500, window_frame(2.0)),
        (lambda w: scene("phone"), 1500, window_frame(1.2)),
    ]

    def run(index=0):
        if index == len(script):
            app.quit()
            return False
        action, wait, capture = script[index]
        action(app.window)

        def shoot():
            capture(app.window)
            GLib.timeout_add(150, run, index + 1)
            return False

        GLib.timeout_add(wait, shoot)
        return False

    def activated(_app):
        def start():
            app.window.sidebar.set_location(str(Path.home() / ".local/share/ibr/backups"))
            run()
            return False
        GLib.timeout_add(1500, start)

    app.connect("activate", activated)
    app.run([sys.argv[0]])
    return frames


def encode(frames: list[tuple[Path, float]]):
    listing = FRAMES / "frames.txt"
    lines = [f"file '{path}'\nduration {seconds}" for path, seconds in frames]
    lines.append(f"file '{frames[-1][0]}'")
    listing.write_text("\n".join(lines) + "\n")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    graph = ("fps=12,scale=960:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=160:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", graph, "-loop", "0", str(OUTPUT)], check=True)


if __name__ == "__main__":
    captured = main()
    encode(captured)
    shutil.rmtree(FRAMES, ignore_errors=True)
    print(f"{OUTPUT} ({OUTPUT.stat().st_size / 1e6:.1f} MB, {len(captured)} frames)")
