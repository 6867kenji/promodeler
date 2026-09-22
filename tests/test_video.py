import os
import tempfile
import unittest

from PIL import Image

from promodeler.video import encode_frames


class VideoTests(unittest.TestCase):
    def test_encodes_frame_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = os.path.join(tmp, "walk_front")
            os.makedirs(frames)
            for i in range(1, 4):
                Image.new("RGB", (32, 24), (i * 40, 0, 0)).save(os.path.join(frames, f"frame_{i:04d}.png"))
            result = encode_frames(frames, 24, os.path.join(tmp, "walk_front"))
            self.assertTrue(result["written"])
            self.assertIn(result["format"], ("mp4", "webp"))
            self.assertEqual(result["frames"], 3)
            self.assertTrue(os.path.getsize(result["path"]) > 0)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(encode_frames(tmp, 24, os.path.join(tmp, "x"))["written"])


if __name__ == "__main__":
    unittest.main()
