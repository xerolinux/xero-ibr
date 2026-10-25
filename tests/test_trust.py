from ibr.services.devices import trust_message


def test_passcode_message():
    assert "passcode" in trust_message("ERROR: Could not validate with device X because a passcode is set.")


def test_declined_message():
    assert "declined" in trust_message("ERROR: Device X said that the user denied the trust dialog.")


def test_default_message():
    assert trust_message("ERROR: Please accept the trust dialog on the screen of device X") == \
        "Tap Trust on your device and enter its passcode."
