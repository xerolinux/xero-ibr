import json
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
    build: str | None = None

    @property
    def spec(self) -> ModelSpec:
        return lookup(self.product_type or "", "iPhone")

    @classmethod
    def from_device(cls, info) -> "FirmwareTarget":
        return cls(info.name, info.product_type, info.os_label.split(" ")[0], info.os_label, udid=info.udid,
                   build=info.build)

    @classmethod
    def from_recovery(cls, mode: str, product_type: str | None, name: str | None, ecid: str | None):
        os_name = "iPadOS" if (product_type or "").startswith("iPad") else "iOS"
        return cls(name or "Your device", product_type, os_name, f"{mode} mode", ecid=ecid)


@dataclass(frozen=True)
class SignedIpsw:
    version: str
    build: str
    filename: str
    url: str
    size: int | None
    sha256: str | None


def signed_ipsws(data: bytes) -> list[SignedIpsw]:
    """Firmwares Apple still signs, from an api.ipsw.me v4 device listing."""
    try:
        firmwares = json.loads(data).get("firmwares", [])
    except (ValueError, AttributeError):
        return []
    found = []
    for item in firmwares:
        if not isinstance(item, dict) or item.get("signed") is not True:
            continue
        url, version, build = item.get("url"), item.get("version"), item.get("buildid")
        if not (isinstance(url, str) and url.endswith(".ipsw") and version and build):
            continue
        size = item.get("filesize")
        found.append(SignedIpsw(str(version), str(build), url.rsplit("/", 1)[-1], url,
                                size if isinstance(size, int) else None, item.get("sha256sum")))
    return found


def _build_order(build: str) -> tuple:
    match = re.match(r"(\d+)([A-Z])(\d+)([a-z]?)$", build)
    if not match:
        return (0, "", 0, 0)
    number = int(match[3])
    final = not match[4] and number < 5000
    return (int(match[1]), match[2], final, number)


def appledb_candidates(index: bytes, os_name: str) -> list[str]:
    """AppleDB firmware keys for real devices in the newest major release, where betas and RCs live."""
    try:
        keys = json.loads(index)
    except ValueError:
        return []
    if not isinstance(keys, list):
        return []
    builds = [k for k in keys if isinstance(k, str) and re.fullmatch(rf"{os_name};\d+[A-Z]\d+[a-z]?", k)]
    if not builds:
        return []
    newest = max(_build_order(k.split(";")[1])[0] for k in builds)
    return [k for k in builds if _build_order(k.split(";")[1])[0] == newest]


def appledb_signed_ipsw(data: bytes, product_type: str) -> SignedIpsw | None:
    """The restore image of an AppleDB firmware entry, when Apple signs it for product_type."""
    try:
        entry = json.loads(data)
    except ValueError:
        return None
    if not isinstance(entry, dict) or product_type not in (entry.get("signed") or []):
        return None
    for source in entry.get("sources") or []:
        if source.get("type") != "ipsw" or product_type not in source.get("deviceMap", []):
            continue
        url = next((link.get("url") for link in source.get("links", [])
                    if str(link.get("url", "")).startswith("https://")), None)
        if url and url.endswith(".ipsw"):
            size = source.get("size")
            return SignedIpsw(str(entry.get("version", "")), str(entry.get("build", "")), url.rsplit("/", 1)[-1],
                              url, size if isinstance(size, int) else None, source.get("hashes", {}).get("sha2-256"))
    return None


def merge_signed(*lists: list[SignedIpsw]) -> list[SignedIpsw]:
    unique = {ipsw.build: ipsw for items in lists for ipsw in items}
    return sorted(unique.values(), key=lambda ipsw: _build_order(ipsw.build), reverse=True)


def _latest_release(signed: list[SignedIpsw]) -> int | None:
    return next((i for i, ipsw in enumerate(signed) if not re.search(r"\b(beta|RC)\b", ipsw.version, re.I)), None)


def ipsw_choices(signed: list[SignedIpsw], installed_build: str | None) -> list[str]:
    latest = _latest_release(signed)
    tags = {latest: " · latest release"}
    return [f"{ipsw.version} ({ipsw.build})" + (" · installed" if ipsw.build == installed_build else tags.get(i, ""))
            for i, ipsw in enumerate(signed)]


def default_choice(signed: list[SignedIpsw], installed_build: str | None) -> int:
    """Reinstalling the installed build is the safe pick; otherwise the newest public release."""
    installed = next((i for i, ipsw in enumerate(signed) if ipsw.build == installed_build), None)
    if installed is not None:
        return installed
    latest = _latest_release(signed)
    return latest if latest is not None else 0


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
