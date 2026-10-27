import json
import re
from dataclasses import dataclass
from pathlib import Path

_ARTWORK_SIZE = re.compile(r"/\d+x\d+bb\.\w+$")


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    duration: float


def track_from_tags(tags: dict, filename: str, duration: float) -> Track:
    title = str(tags.get("title") or "").strip() or Path(filename).stem
    return Track(title, str(tags.get("artist") or "").strip(), str(tags.get("album") or "").strip(), duration)


def artwork_query(track: Track) -> dict | None:
    """iTunes Search parameters for a track's cover, or None when there is too little to search for."""
    if not track.artist:
        return None
    if track.album:
        return {"term": f"{track.artist} {track.album}", "entity": "album", "limit": "5"}
    return {"term": f"{track.artist} {track.title}", "entity": "song", "limit": "5"}


def itunes_artwork(data: bytes, artist: str) -> str | None:
    """The first result by the same artist, asking for a 600 px image."""
    try:
        results = json.loads(data).get("results", [])
    except (ValueError, AttributeError):
        return None
    wanted = artist.casefold()
    for result in results:
        if not isinstance(result, dict) or str(result.get("artistName", "")).casefold() != wanted:
            continue
        url = result.get("artworkUrl100")
        if url and _ARTWORK_SIZE.search(url):
            return _ARTWORK_SIZE.sub("/600x600bb.jpg", url)
    return None
