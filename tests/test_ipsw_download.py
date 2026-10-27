import hashlib

from ibr.services.firmware import download_ipsw


def test_download_verifies_and_renames(tmp_path):
    source = tmp_path / "src.ipsw"
    source.write_bytes(b"x" * 300_000)
    target = tmp_path / "out" / "iPhone.ipsw"
    seen = []
    error = download_ipsw(source.as_uri(), target, hashlib.sha256(source.read_bytes()).hexdigest(),
                          lambda done, total: seen.append((done, total)), lambda: False)
    assert error is None
    assert target.read_bytes() == source.read_bytes()
    assert seen[-1] == (300_000, 300_000)
    assert not list((tmp_path / "out").glob("*.part"))


def test_download_rejects_a_damaged_file(tmp_path):
    source = tmp_path / "src.ipsw"
    source.write_bytes(b"abc")
    target = tmp_path / "iPhone.ipsw"
    error = download_ipsw(source.as_uri(), target, "0" * 64, lambda *_: None, lambda: False)
    assert error and "damaged" in error
    assert not target.exists() and not list(tmp_path.glob("*.part"))


def test_cancel_leaves_nothing(tmp_path):
    source = tmp_path / "src.ipsw"
    source.write_bytes(b"x" * 3_000_000)
    target = tmp_path / "iPhone.ipsw"
    assert download_ipsw(source.as_uri(), target, None, lambda *_: None, lambda: True) == "Cancelled"
    assert not target.exists() and not list(tmp_path.glob("*.part"))
