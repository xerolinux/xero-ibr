import shutil
import subprocess

import gi
import pytest

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from ibr.services.thumbnails import render  # noqa: E402


def size_of(path):
    image = GdkPixbuf.Pixbuf.new_from_file(str(path))
    return image.get_width(), image.get_height()


def test_image_is_scaled_down_keeping_its_shape(tmp_path):
    source = tmp_path / "photo.png"
    GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 1000, 500).savev(str(source), "png", [], [])
    target = tmp_path / "out" / "thumb.png"
    assert render(source, "photo.png", target, 256)
    assert size_of(target) == (256, 128)


def test_unknown_file_gives_no_thumbnail(tmp_path):
    source = tmp_path / "notes.zzz"
    source.write_bytes(b"plain")
    assert not render(source, "notes.zzz", tmp_path / "t.png", 256)
    assert not (tmp_path / "t.png").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg to make a sample video")
def test_video_frame(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                    "-pix_fmt", "yuv420p", str(source)], check=True)
    target = tmp_path / "thumb.png"
    assert render(source, "clip.mp4", target, 256)
    assert size_of(target) == (256, 192)
