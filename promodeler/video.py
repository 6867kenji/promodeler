"""Encode rendered clip frames into a video file on the host.

Blender builds without FFmpeg support (the Blender 5.1 build on this
machine is one) cannot write .mp4 directly, so the kernel renders a PNG
frame sequence and this module encodes it: with ``ffmpeg`` on PATH (or
``imageio_ffmpeg`` installed) to H.264 .mp4, otherwise to an animated
.webp with Pillow. The frames stay next to the video for inspection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def ffmpeg_executable() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def encode_frames(frames_dir: str | Path, fps: int, stem: str | Path) -> dict:
    """Encode ``frames_dir/frame_####.png`` to ``<stem>.mp4`` (ffmpeg) or ``<stem>.webp`` (Pillow)."""
    frames_dir = Path(frames_dir)
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        return {"path": None, "written": False, "format": None, "encoder": None, "frames": 0}
    ffmpeg = ffmpeg_executable()
    if ffmpeg:
        path = Path(f"{stem}.mp4")
        command = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames_dir / "frame_%04d.png"),
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(path)]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode == 0 and path.is_file():
            return {"path": str(path), "written": True, "format": "mp4", "encoder": "ffmpeg", "frames": len(frames)}
    try:
        from PIL import Image
    except ImportError:
        return {"path": None, "written": False, "format": None, "encoder": None, "frames": len(frames),
                "error": "neither ffmpeg nor Pillow is available to encode the frames"}
    path = Path(f"{stem}.webp")
    images = [Image.open(f).convert("RGB") for f in frames]
    try:
        images[0].save(path, save_all=True, append_images=images[1:], duration=int(round(1000 / fps)), loop=0,
                       quality=85, method=4)
    finally:
        for image in images:
            image.close()
    written = path.is_file() and os.path.getsize(path) > 0
    return {"path": str(path), "written": written, "format": "webp", "encoder": "pillow", "frames": len(frames)}
