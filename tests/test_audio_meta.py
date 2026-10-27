import json

from ibr.core.audio_meta import Track, artwork_query, itunes_artwork, track_from_tags


def test_track_from_tags():
    track = track_from_tags({"title": "Desert Road", "artist": "The Long Hours", "album": "Night Drives"},
                            "01 Desert Road.m4a", 225.4)
    assert track == Track("Desert Road", "The Long Hours", "Night Drives", 225.4)


def test_track_title_falls_back_to_file_name():
    assert track_from_tags({}, "Voice Memo 14.m4a", 48.0) == Track("Voice Memo 14", "", "", 48.0)


def test_artwork_query_needs_artist():
    assert artwork_query(Track("Song", "", "", 1.0)) is None
    album = {"term": "Band Record", "entity": "album", "limit": "5"}
    assert artwork_query(Track("Song", "Band", "Record", 1.0)) == album
    assert artwork_query(Track("Song", "Band", "", 1.0)) == {"term": "Band Song", "entity": "song", "limit": "5"}


def test_itunes_artwork_prefers_matching_artist_and_asks_for_large_image():
    data = json.dumps({"results": [
        {"artistName": "Someone Else", "artworkUrl100": "https://x.mzstatic.com/a/100x100bb.jpg"},
        {"artistName": "The Long Hours", "artworkUrl100": "https://x.mzstatic.com/b/100x100bb.jpg"},
    ]}).encode()
    assert itunes_artwork(data, "the long hours") == "https://x.mzstatic.com/b/600x600bb.jpg"
    assert itunes_artwork(data, "nobody") is None
    assert itunes_artwork(b"junk", "x") is None
