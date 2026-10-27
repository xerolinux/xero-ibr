import hashlib
import shutil
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import __version__
from ..core.firmware import (appledb_candidates, appledb_signed_ipsw, ipsw_devices, merge_signed, signed_ipsws,
                             tool_is_modern)
from .runner import in_thread, run


def check_tool(callback):
    """callback(state) where state is "missing", "old" or "ok"."""
    if shutil.which("idevicerestore") is None:
        callback("missing")
        return
    run(["idevicerestore", "--help"],
        lambda status, out, err: callback("ok" if tool_is_modern((out + err).decode(errors="replace")) else "old"))


def _get(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": f"iBR/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read()
    except (OSError, ValueError):
        return None


def fetch_signed(product_type: str, callback):
    """callback(list[SignedIpsw]) with every build Apple signs for product_type, betas and RCs included
    (ipsw.me lists releases, AppleDB adds betas), or callback(None) when offline."""
    def fetch():
        releases = _get(f"https://api.ipsw.me/v4/device/{urllib.parse.quote(product_type, safe=',')}?type=ipsw")
        index = _get("https://api.appledb.dev/ios/index.json")
        if releases is None and index is None:
            return None
        keys = appledb_candidates(index or b"", "iPadOS" if product_type.startswith("iPad") else "iOS")
        with ThreadPoolExecutor(8) as pool:
            entries = pool.map(lambda key: _get(f"https://api.appledb.dev/ios/{urllib.parse.quote(key, safe=';')}.json"),
                               keys)
            betas = [ipsw for data in entries if data and (ipsw := appledb_signed_ipsw(data, product_type))]
        return merge_signed(signed_ipsws(releases or b""), betas)

    in_thread(fetch, callback)


def fetch_devices(callback):
    """callback(list of (identifier, name)) for every supported iPhone and iPad, or callback([]) when offline."""
    in_thread(lambda: ipsw_devices(_get("https://api.ipsw.me/v4/devices") or b""), callback)


_CHUNK = 1 << 20


def download_ipsw(url: str, target: Path, sha256: str | None, progress, cancelled) -> str | None:
    """Blocking: downloads to target, checking the SHA-256 when known. progress(done, total) after each chunk;
    cancelled() is polled. Returns None on success, else what went wrong. Nothing is left behind on failure."""
    target = Path(target)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": f"iBR/{__version__}"})
        with urllib.request.urlopen(request, timeout=30) as response, open(partial, "wb") as out:
            length = response.headers.get("Content-Length")
            total, done = int(length) if length and length.isdigit() else None, 0
            while chunk := response.read(_CHUNK):
                if cancelled():
                    raise InterruptedError
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
        if sha256 and digest.hexdigest() != sha256.lower():
            partial.unlink(missing_ok=True)
            return "The download is damaged (its checksum does not match Apple's). Try again."
        partial.replace(target)
        return None
    except InterruptedError:
        partial.unlink(missing_ok=True)
        return "Cancelled"
    except (OSError, ValueError) as error:
        partial.unlink(missing_ok=True)
        return f"The download failed: {getattr(error, 'reason', None) or error}"
