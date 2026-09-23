"""Clip recording plumbing on the Python side: batch flags, clip-list parsing and frame encoding (GIF via Pillow)."""

import tempfile
import unittest
from pathlib import Path

from promodeler.character import bridge
from promodeler.character.cli import _clip_list


class ClipFlagTests(unittest.TestCase):
    def test_clip_list_parsing(self):
        self.assertIsNone(_clip_list(None))
        self.assertEqual(_clip_list("all"), ())
        self.assertEqual(_clip_list(""), ())
        self.assertEqual(_clip_list("idle, walk"), ("idle", "walk"))

    def test_batch_command_carries_the_clip_flags(self):
        staged = bridge.Staged(out_dir=Path("out"), hash="h", recipe_path=Path("out/recipe.json"), outfit_path=None, assets={})
        plain = bridge.batch_command("Unity", staged, ("front",), ("shaded",), ("glb",), True)
        self.assertNotIn("-clips", plain)
        every = bridge.batch_command("Unity", staged, ("front",), ("shaded",), ("glb",), True, clips=(), clip_fps=8, clip_seconds=1.5)
        self.assertEqual(every[every.index("-clips") + 1], "all")
        self.assertEqual(every[every.index("-clip-fps") + 1], "8")
        self.assertEqual(every[every.index("-clip-seconds") + 1], "1.5")
        some = bridge.batch_command("Unity", staged, ("front",), ("shaded",), ("glb",), True, clips=("idle", "sit"))
        self.assertEqual(some[some.index("-clips") + 1], "idle,sit")


class EncodeClipTests(unittest.TestCase):
    def test_frames_become_a_gif_when_ffmpeg_is_absent(self):
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "clips" / "idle"
            directory.mkdir(parents=True)
            for i in range(4):
                Image.new("RGB", (16, 16), (i * 60, 30, 90)).save(directory / f"f_{i:04d}.png")
            original = bridge.find_ffmpeg
            bridge.find_ffmpeg = lambda: None
            try:
                added = bridge.encode_clip({"id": "idle", "directory": str(directory), "fps": 4, "loop": True})
            finally:
                bridge.find_ffmpeg = original
            self.assertEqual(added["video_format"], "gif")
            self.assertEqual(added["encoder"], "pillow")
            self.assertTrue(Path(added["video"]).is_file())
            self.assertEqual(Path(added["video"]).name, "idle.gif")
            with Image.open(added["video"]) as gif:
                self.assertEqual(getattr(gif, "n_frames", 1), 4)

    def test_no_frames_gives_no_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bridge.encode_clip({"id": "x", "directory": tmp, "fps": 10}), {"video": None, "video_format": None})


if __name__ == "__main__":
    unittest.main()
