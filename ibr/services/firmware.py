import shutil
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request

from .. import __version__
from ..core.firmware import appledb_candidates, appledb_signed_ipsw, merge_signed, signed_ipsws, tool_is_modern
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
