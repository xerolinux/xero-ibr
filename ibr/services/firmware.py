import shutil

from ..core.firmware import tool_is_modern
from .runner import run


def check_tool(callback):
    """callback(state) where state is "missing", "old" or "ok"."""
    if shutil.which("idevicerestore") is None:
        callback("missing")
        return
    run(["idevicerestore", "--help"],
        lambda status, out, err: callback("ok" if tool_is_modern((out + err).decode(errors="replace")) else "old"))
