import re
from dataclasses import dataclass

from .catalog import ModelSpec, lookup
from .progress import Error, Finished


@dataclass(frozen=True)
class StepChanged:
    index: int
    name: str


@dataclass(frozen=True)
class OverallPercent:
    value: float


@dataclass(frozen=True)
class FirmwareTarget:
    name: str
    product_type: str | None
    os_name: str
    installed: str
    udid: str | None = None
    ecid: str | None = None

    @property
    def spec(self) -> ModelSpec:
        return lookup(self.product_type or "", "iPhone")

    @classmethod
    def from_device(cls, info) -> "FirmwareTarget":
        return cls(info.name, info.product_type, info.os_label.split(" ")[0], info.os_label, udid=info.udid)

    @classmethod
    def from_recovery(cls, mode: str, product_type: str | None, name: str | None, ecid: str | None):
        os_name = "iPadOS" if (product_type or "").startswith("iPad") else "iOS"
        return cls(name or "Your device", product_type, os_name, f"{mode} mode", ecid=ecid)


def ipsw_matches(filename: str, product_type: str) -> bool | None:
    """True or False when the file name lists model identifiers, None when it was renamed and cannot tell."""
    models = re.findall(r"(?:iPhone|iPad|iPod)\d+,\d+", filename)
    return product_type in models if models else None


def tool_is_modern(help_text: str) -> bool:
    """Builds that know --plain-progress and --variant handle the iOS 15+ restore protocol and Cryptex1."""
    return "--plain-progress" in help_text and "--variant" in help_text


# idevicerestore's RESTORE_STEP_* order; weights reflect how long each step usually takes.
_STEPS = (
    ("Checking the device", 5),
    ("Preparing the firmware", 10),
    ("Sending iOS to the device", 45),
    ("Verifying iOS", 15),
    ("Updating firmware", 15),
    ("Updating the modem", 5),
    ("Finishing up", 2),
    ("Sending boot images", 3),
)
_PROGRESS = re.compile(r"^progress: (\d+) ([\d.]+)$")
_FAILED_STATUS = re.compile(r"^Status: (?!Restore Finished)(.+?)\.?$")


class FirmwareParser:
    def __init__(self):
        self._buffer = ""
        self._step = None
        self._overall = 0.0
        self.last_line = ""

    def feed(self, chunk: str) -> list:
        self._buffer += chunk
        *lines, self._buffer = re.split(r"[\r\n]", self._buffer)
        events = []
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            self.last_line = line
            events += self._line(line)
        return events

    def _line(self, line: str) -> list:
        match = _PROGRESS.match(line)
        if match:
            index, fraction = int(match.group(1)), float(match.group(2))
            events = []
            if 0 <= index < len(_STEPS):
                if index != self._step:
                    self._step = index
                    events.append(StepChanged(index, _STEPS[index][0]))
                overall = sum(weight for _, weight in _STEPS[:index]) + _STEPS[index][1] * min(fraction, 1.0)
                if overall > self._overall:
                    self._overall = overall
                    events.append(OverallPercent(overall))
            return events
        if line == "DONE" or line == "Status: Restore Finished":
            return [Finished(True, "Restore Finished" if line.startswith("Status") else "DONE")]
        failed = _FAILED_STATUS.match(line)
        if failed:
            return [Finished(False, failed.group(1))]
        if line.startswith("ERROR: "):
            return [Error(line[len("ERROR: "):])]
        return []
