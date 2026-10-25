import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    name: str


@dataclass(frozen=True)
class Percent:
    value: float


@dataclass(frozen=True)
class Bytes:
    done: int
    total: int


@dataclass(frozen=True)
class Sent:
    size: int


@dataclass(frozen=True)
class Copied:
    path: str


@dataclass(frozen=True)
class Finished:
    success: bool
    message: str


@dataclass(frozen=True)
class Error:
    message: str


_SPLIT = re.compile(r"[\r\n]")
_PERCENT = re.compile(r"\]\s*(\d+(?:\.\d+)?)%\s*Finished")
_SENDING = re.compile(r"^Sending '.*' \((\d+(?:\.\d+)?\s*[A-Za-z]+)\)$")
_BYTES = re.compile(r"\((\d+(?:\.\d+)?\s*[A-Za-z]+)/(\d+(?:\.\d+)?\s*[A-Za-z]+)\)")
_COPYING = re.compile(r"^Copying '.*' to '(.*)'$")
_SUCCESS = re.compile(
    r"^(?:(?:Backup|Restore|Operation|Unback) Successful"
    r"|Backup encryption has been (?:enabled|disabled) successfully"
    r"|Backup encryption password has been changed successfully)\.$")
_FAILURE = re.compile(
    r"^(?:(?:Backup|Restore) Failed \(Error Code -?\d+\)"
    r"|(?:Backup|Restore|Operation) Aborted|Operation Failed"
    r"|Could not (?:enable|disable) backup encryption"
    r"|Could not change backup encryption password)\.$")
_PHASES = (
    ("Starting backup", "starting"),
    ("Starting Restore", "starting"),
    ("Requesting backup from device", "starting"),
    ("*** Waiting for passcode", "passcode"),
    ("Receiving files", "receiving"),
    ("Sending '", "sending"),
)
_ERROR_PREFIXES = ("ERROR: ", "Received an error message from device: ")
_CANCELLED = "User has cancelled the backup process on the device."
_UNITS = {"bytes": 1, "b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12}


def parse_size(text: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", text)
    if not match:
        return None
    factor = _UNITS.get(match.group(2).lower())
    if factor is None:
        return None
    return round(float(match.group(1)) * factor)


class ProgressParser:
    def __init__(self):
        self._buffer = ""
        self._phase = None
        self._percent = None
        self._bytes = None
        self.last_line = ""

    def feed(self, chunk: str) -> list:
        self._buffer += chunk
        parts = _SPLIT.split(self._buffer)
        self._buffer = parts.pop()
        events = []
        for line in parts:
            self._live(line, events)
            self._final(line.strip(), events)
        self._live(self._buffer, events)
        return events

    def _live(self, line: str, events: list):
        for prefix, name in _PHASES:
            if line.lstrip().startswith(prefix) and name != self._phase:
                self._phase = name
                events.append(Phase(name))
                break
        match = _PERCENT.search(line)
        if match:
            value = float(match.group(1))
            if value != self._percent:
                self._percent = value
                events.append(Percent(value))
        match = _BYTES.search(line)
        if match:
            done, total = parse_size(match.group(1)), parse_size(match.group(2))
            if done is not None and total is not None and (done, total) != self._bytes:
                self._bytes = (done, total)
                events.append(Bytes(done, total))

    def _final(self, line: str, events: list):
        if line and not line.startswith("["):
            self.last_line = line
        sending = _SENDING.match(line)
        copying = _COPYING.match(line)
        if copying:
            events.append(Copied(copying.group(1)))
        elif sending:
            size = parse_size(sending.group(1))
            if size is not None:
                events.append(Sent(size))
        elif _SUCCESS.match(line):
            events.append(Finished(True, line))
        elif _FAILURE.match(line):
            events.append(Finished(False, line))
        elif line == _CANCELLED:
            events.append(Error(line))
        else:
            for prefix in _ERROR_PREFIXES:
                if line.startswith(prefix):
                    events.append(Error(line[len(prefix):]))
                    break


class TransferCounter:
    def __init__(self):
        self._base = 0
        self._sent = 0
        self._batch = None

    def batch(self, done: int, total: int) -> int:
        if self._batch is not None:
            last_done, last_total = self._batch
            if done < last_done or total != last_total:
                self._base += last_done
        self._batch = (done, total)
        return self.total

    def sent(self, size: int) -> int:
        self._sent += size
        return self.total

    @property
    def total(self) -> int:
        return self._base + self._sent + (self._batch[0] if self._batch else 0)


class SpeedMeter:
    _SMOOTHING = 0.3

    def __init__(self):
        self._last = None
        self.speed = None

    def update(self, done: int, now: float):
        if self._last is not None:
            last_done, last_time = self._last
            elapsed = now - last_time
            if elapsed <= 0:
                return
            rate = (done - last_done) / elapsed
            if self.speed is None:
                self.speed = rate
            else:
                self.speed = self._SMOOTHING * rate + (1 - self._SMOOTHING) * self.speed
        self._last = (done, now)

    def eta(self, total: int, done: int) -> float | None:
        if not self.speed or self.speed <= 0:
            return None
        return max(total - done, 0) / self.speed
