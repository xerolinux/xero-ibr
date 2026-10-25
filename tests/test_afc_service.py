from ibr.services.afc import Afc


def test_command_separates_afcclient_options():
    assert Afc("U1")._argv("ls", "-l", "/") == ["afcclient", "-u", "U1", "--", "ls", "-l", "/"]
    assert Afc("U1", "org.app")._argv("put", "-rf", "--", "a", "/a") == [
        "afcclient", "-u", "U1", "--documents", "org.app", "--", "put", "-rf", "--", "a", "/a"]
