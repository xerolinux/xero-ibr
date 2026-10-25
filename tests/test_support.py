import pytest

from ibr.core.support import MIN_OS_LABEL, is_supported


@pytest.mark.parametrize("version", ["15.0", "15.8.4", "16.7", "18.6.2", "26.0.1", "27.0", "40"])
def test_supported(version):
    assert is_supported(version)


@pytest.mark.parametrize("version", ["14.8.1", "12.5.7", "9.3.5"])
def test_unsupported(version):
    assert not is_supported(version)


def test_unparsable_version_is_not_blocked():
    assert is_supported("")
    assert is_supported("beta")


def test_label():
    assert MIN_OS_LABEL == "iOS 15 / iPadOS 15"
