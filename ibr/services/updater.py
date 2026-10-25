import hashlib
import os
import platform
import subprocess
import urllib.request
from pathlib import Path

from gi.repository import GLib

from .. import __version__
from ..constants import UPDATE_REPO
from ..core.update import UpdateInfo, clean_env, pick_update
from .runner import in_thread

_HEADERS = {"User-Agent": f"iBR/{__version__}", "Accept": "application/vnd.github+json"}


def running_appimage() -> Path | None:
    """The AppImage file this process runs from, when it can be replaced in place."""
    path = Path(os.environ.get("APPIMAGE", ""))
    if not UPDATE_REPO or not path.is_file():
        return None
    if not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK):
        return None
    return path


def check(callback):
    """callback(UpdateInfo | None) on the main loop."""
    if running_appimage() is None:
        return

    def work():
        request = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                         headers=_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return pick_update(response.read(), platform.machine(), __version__)
        except OSError:
            return None

    in_thread(work, callback)


def install(info: UpdateInfo, progress, done):
    """Downloads, verifies and swaps the AppImage. progress(fraction) and done(error | None) run on the main loop."""
    target = running_appimage()
    if target is None:
        done("This copy of iBR cannot update itself.")
        return
    partial = target.with_name(target.name + ".new")

    def work():
        digest = hashlib.sha256()
        received = 0
        try:
            request = urllib.request.Request(info.url, headers={"User-Agent": _HEADERS["User-Agent"]})
            with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if info.size:
                        GLib.idle_add(lambda value=received / info.size: progress(value) and False)
            if info.size and received != info.size:
                raise OSError("the download was incomplete")
            if info.sha256 and digest.hexdigest() != info.sha256:
                raise OSError("the download did not match the published checksum")
            partial.chmod(0o755)
            os.replace(partial, target)
        except OSError as error:
            partial.unlink(missing_ok=True)
            return str(getattr(error, "reason", error))
        return None

    in_thread(work, done)


def relaunch_after_exit():
    """Starts the updated AppImage once this process has exited, so the single-instance check passes."""
    target = running_appimage()
    if target is None:
        return
    env = clean_env(dict(os.environ), os.environ.get("APPDIR", "/nonexistent"))
    subprocess.Popen(["/bin/sh", "-c", 'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; exec "$2"',
                      "ibr-update", str(os.getpid()), str(target)],
                     env=env, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
