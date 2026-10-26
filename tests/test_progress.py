from ibr.core.progress import (
    Bytes,
    Error,
    connection_dropped,
    explain_failure,
    Finished,
    Percent,
    Phase,
    ProgressParser,
    Sent,
    SpeedMeter,
    TransferCounter,
    parse_size,
)


def feed_all(*chunks):
    parser = ProgressParser()
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    return events


def test_overall_percent_line():
    assert Percent(42.0) in feed_all("[=====     ]  42% Finished\n")


def test_overall_percent_waits_for_finished_suffix():
    parser = ProgressParser()
    assert parser.feed("\r[=====     ]  42%") == []
    assert parser.feed(" Finished\n") == [Percent(42.0)]


def test_repeated_percent_not_duplicated():
    events = feed_all("\r[==  ]  10% Finished\n", "\r[==  ]  10% Finished\n", "\r[===  ]  11% Finished\n")
    assert [e for e in events if isinstance(e, Percent)] == [Percent(10.0), Percent(11.0)]


def test_batch_progress_gives_bytes_not_percent():
    events = feed_all("Receiving files\n", "\r[=====     ]  10% (1.2 GB/12.0 GB)     ")
    assert Phase("receiving") in events
    assert Bytes(1_200_000_000, 12_000_000_000) in events
    assert not [e for e in events if isinstance(e, Percent)]


def test_bytes_in_small_units():
    assert Bytes(512, 2048) in feed_all("\r[=] 25% (512 Bytes/2048 Bytes)     ")


def test_sending_file_reports_size():
    assert Sent(40_000_000) in feed_all("Sending 'Manifest.db' (40.0 MB)\n")


def test_transfer_counter_sums_batches():
    counter = TransferCounter()
    assert counter.batch(100, 300) == 100
    assert counter.batch(300, 300) == 300
    assert counter.batch(50, 200) == 350
    assert counter.batch(200, 200) == 500


def test_transfer_counter_new_batch_with_same_total():
    counter = TransferCounter()
    counter.batch(300, 300)
    assert counter.batch(10, 300) == 310


def test_transfer_counter_sent_files():
    counter = TransferCounter()
    assert counter.sent(40) == 40
    assert counter.sent(60) == 100


def test_phases():
    events = feed_all(
        "Starting backup...\n",
        "*** Waiting for passcode to be entered on the device ***\n",
        "Sending 'Manifest.db' (40.0 MB)\n",
        "Starting Restore...\n",
    )
    assert [e.name for e in events if isinstance(e, Phase)] == [
        "starting",
        "passcode",
        "sending",
        "starting",
    ]


def test_backup_success():
    assert Finished(True, "Backup Successful.") in feed_all("Backup Successful.\n")


def test_restore_success():
    assert Finished(True, "Restore Successful.") in feed_all("Restore Successful.\n")


def test_backup_failure():
    events = feed_all("Backup Failed (Error Code -4).\n")
    assert Finished(False, "Backup Failed (Error Code -4).") in events


def test_error_lines():
    events = feed_all(
        "ERROR: Could not start backup process: device refused to start the backup process.\n",
        "Received an error message from device: Device locked\n",
        "User has cancelled the backup process on the device.\n",
    )
    assert [e.message for e in events if isinstance(e, Error)] == [
        "Could not start backup process: device refused to start the backup process.",
        "Device locked",
        "User has cancelled the backup process on the device.",
    ]


def test_crlf_and_split_chunks():
    events = feed_all("Backup Succ", "essful.\r\n")
    assert Finished(True, "Backup Successful.") in events


def test_parse_size():
    assert parse_size("1.5 KB") == 1500
    assert parse_size("3 Bytes") == 3
    assert parse_size("2.0 TB") == 2_000_000_000_000
    assert parse_size("nonsense") is None


def test_speed_meter_eta():
    meter = SpeedMeter()
    meter.update(0, 0.0)
    meter.update(100_000_000, 10.0)
    assert meter.speed == 10_000_000
    assert meter.eta(200_000_000, 100_000_000) == 10.0


def test_speed_meter_no_data():
    meter = SpeedMeter()
    assert meter.speed is None
    assert meter.eta(10, 0) is None


def test_last_line_skips_progress_bars():
    parser = ProgressParser()
    parser.feed("No device found with udid X.\n\r[====]  10% (1 MB/2 MB)     \n")
    assert parser.last_line == "No device found with udid X."


def test_encryption_and_password_results():
    from ibr.core.progress import Finished as F
    assert F(True, "Backup encryption has been enabled successfully.") in feed_all(
        "Backup encryption has been enabled successfully.\n")
    assert F(True, "Backup encryption has been disabled successfully.") in feed_all(
        "Backup encryption has been disabled successfully.\n")
    assert F(True, "Backup encryption password has been changed successfully.") in feed_all(
        "Backup encryption password has been changed successfully.\n")
    assert F(False, "Could not enable backup encryption.") in feed_all("Could not enable backup encryption.\n")
    assert F(False, "Could not change backup encryption password.") in feed_all(
        "Could not change backup encryption password.\n")


def test_aborted_is_failure():
    assert Finished(False, "Restore Aborted.") in feed_all("Restore Aborted.\n")
    assert Finished(False, "Backup Aborted.") in feed_all("Backup Aborted.\n")


def test_copy_item_reported():
    from ibr.core.progress import Copied
    assert Copied("ab/abcdef") in feed_all("Copying 'aa/123' to 'ab/abcdef'\n")


def test_explain_failure_connection_drop():
    text = explain_failure("Could not receive from mobilebackup2 (-4)")
    assert "connection" in text.lower() and "cable" in text.lower()
    assert explain_failure("Could not receive from mobilebackup2 (-3)") == text
    assert explain_failure("Backup Aborted.") == "Backup Aborted."


def test_connection_dropped():
    assert connection_dropped("Could not receive from mobilebackup2 (-4)")
    assert connection_dropped("ERROR: Could not receive from mobilebackup2 (-3)")
    assert not connection_dropped("Could not receive from mobilebackup2 (-5)")
    assert not connection_dropped("Cancelled")
