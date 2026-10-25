import os
import shutil
import threading

import gi

gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib  # noqa: E402

REQUIRED_TOOLS = ("idevice_id", "ideviceinfo", "idevicepair", "idevicebackup2", "afcclient")


def missing_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def _launcher(flags: Gio.SubprocessFlags, env: dict | None) -> Gio.SubprocessLauncher:
    launcher = Gio.SubprocessLauncher.new(flags)
    launcher.setenv("LC_ALL", "C", True)
    for key, value in (env or {}).items():
        launcher.setenv(key, value, True)
    return launcher


def spawn(argv: list[str], env: dict | None = None) -> Gio.Subprocess:
    return _launcher(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE, env).spawnv(argv)


def spawn_pty(argv: list[str], env: dict | None = None) -> tuple[Gio.Subprocess, Gio.InputStream]:
    """Spawn with stdout/stderr on a pseudo-terminal so the tool flushes progress lines as it prints them."""
    master, slave = os.openpty()
    launcher = _launcher(Gio.SubprocessFlags.NONE, env)
    launcher.take_stdout_fd(slave)
    launcher.take_stderr_fd(os.dup(slave))
    try:
        proc = launcher.spawnv(argv)
    except GLib.Error:
        os.close(master)
        raise
    finally:
        launcher.close()
    return proc, GioUnix.InputStream.new(master, True)


def run(argv: list[str], callback, env: dict | None = None):
    """Run argv asynchronously; callback(status: int, stdout: bytes, stderr: bytes)."""
    try:
        proc = spawn(argv, env)
    except GLib.Error as error:
        GLib.idle_add(callback, -1, b"", error.message.encode())
        return

    def finished(proc, result):
        try:
            _, out, err = proc.communicate_finish(result)
        except GLib.Error as error:
            callback(-1, b"", error.message.encode())
            return
        status = proc.get_exit_status() if proc.get_if_exited() else -1
        callback(status, out.get_data() if out else b"", err.get_data() if err else b"")

    proc.communicate_async(None, None, finished)


def in_thread(func, callback):
    """Run func() on a worker thread, then callback(result) on the main loop."""
    def work():
        result = func()
        GLib.idle_add(lambda: callback(result) and False)

    threading.Thread(target=work, daemon=True).start()
