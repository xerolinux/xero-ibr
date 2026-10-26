import time

from gi.repository import GLib

from ibr.services.runner import run


def _wait(argv, **kwargs):
    loop = GLib.MainLoop()
    result = []

    def done(status, out, err):
        result.append((status, out, err))
        loop.quit()

    run(argv, done, **kwargs)
    GLib.timeout_add_seconds(10, loop.quit)
    loop.run()
    return result


def test_run_kills_a_hung_command_after_timeout():
    start = time.monotonic()
    result = _wait(["sleep", "30"], timeout=1)
    assert time.monotonic() - start < 5
    assert result and result[0][0] != 0
    assert b"timed out" in result[0][2]


def test_run_without_timeout_returns_output():
    assert _wait(["echo", "hi"]) == [(0, b"hi\n", b"")]
