import signal
from datetime import datetime
from pathlib import Path

from gi.repository import GLib, GObject

from ..core.progress import Error, Finished, ProgressParser
from ..core.settings import xdg_dir
from .runner import spawn_pty


def log_dir() -> Path:
    return xdg_dir("XDG_STATE_HOME", ".local/state") / "ibr" / "logs"


class Operation(GObject.Object):
    __gsignals__ = {
        "event": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "done": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
    }

    def __init__(self, kind: str, argv: list[str], env: dict | None = None, parser=None):
        super().__init__()
        self.kind = kind
        self._argv = argv
        self._env = env or {}
        self._parser = parser or ProgressParser()
        self._proc = None
        self._log = None
        self._finished: Finished | None = None
        self._last_error = ""
        self.cancelled = False
        self.running = False

    def start(self):
        try:
            folder = log_dir()
            folder.mkdir(parents=True, exist_ok=True)
            self._log = open(folder / f"{datetime.now():%Y%m%d-%H%M%S}-{self.kind}.log", "w", encoding="utf-8")
            self._log.write(" ".join(self._argv) + "\n")
        except OSError:
            self._log = None
        try:
            self._proc, stream = spawn_pty(self._argv, self._env)
        except GLib.Error as error:
            GLib.idle_add(self._done, False, error.message)
            return
        self.running = True
        self._read(stream)

    def cancel(self):
        if not self.running or self.cancelled:
            return
        self.cancelled = True
        self._proc.send_signal(signal.SIGINT)
        GLib.timeout_add_seconds(15, self._force_exit)

    def _force_exit(self):
        if self.running:
            self._proc.force_exit()
        return GLib.SOURCE_REMOVE

    def _read(self, stream):
        stream.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, self._on_read)

    def _on_read(self, stream, result):
        try:
            data = stream.read_bytes_finish(result).get_data()
        except GLib.Error:
            data = b""
        if not data:
            self._proc.wait_async(None, self._on_exit)
            return
        text = data.decode(errors="replace")
        if self._log:
            self._log.write(text)
        for event in self._parser.feed(text):
            if isinstance(event, Finished):
                self._finished = event
            elif isinstance(event, Error):
                self._last_error = event.message
            self.emit("event", event)
        self._read(stream)

    def _on_exit(self, proc, result):
        try:
            proc.wait_finish(result)
        except GLib.Error:
            pass
        status = proc.get_exit_status() if proc.get_if_exited() else -1
        if self.cancelled:
            self._done(False, "Cancelled")
        elif self._finished and self._finished.success and status == 0:
            self._done(True, self._finished.message)
        else:
            message = self._last_error or (self._finished.message if self._finished else self._parser.last_line)
            self._done(False, message or f"{self._argv[0]} exited with status {status}")

    def _done(self, success: bool, message: str):
        self.running = False
        if self._log:
            self._log.write(f"\n[ibr] {'success' if success else 'failed'}: {message}\n")
            self._log.close()
            self._log = None
        self.emit("done", success, message)
