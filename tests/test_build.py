"""Integration test: runs the real headless Blender kernel. Skipped when Blender is unavailable."""

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from promodeler.build import BlenderNotFound, build, find_blender

ROOT = Path(__file__).resolve().parent.parent


def blender_available() -> bool:
    if os.environ.get("PROMODELER_SKIP_BLENDER"):
        return False
    try:
        find_blender()
        return True
    except BlenderNotFound:
        return False


@unittest.skipUnless(blender_available(), "Blender not available")
class BuildTests(unittest.TestCase):
    def test_crate_builds_renders_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(str(ROOT / "assets" / "crate.py"), out_root=tmp, force=True)
            self.assertTrue(result.ok, result.report.get("error"))
            report = result.report
            self.assertEqual(set(report["parts"]), {"body", "handle"})
            self.assertEqual(report["totals"]["non_manifold_edges"], 0)
            # Authoring space is Y up: the crate rests on y = 0 and its handle rises above it.
            self.assertAlmostEqual(report["bounds"]["min"][1], 0.0, places=3)
            self.assertGreater(report["bounds"]["max"][1], 0.5)
            self.assertTrue(all(r["written"] for r in report["renders"]))
            self.assertTrue(report["export"]["written"])
            with open(report["export"]["path"], "rb") as f:
                magic, version, length = struct.unpack("<4sII", f.read(12))
            self.assertEqual(magic, b"glTF")
            self.assertEqual(version, 2)
            self.assertEqual(length, report["export"]["bytes"])
            # Second build hits the cache.
            again = build(str(ROOT / "assets" / "crate.py"), out_root=tmp)
            self.assertTrue(again.cached)
            self.assertEqual(again.hash, result.hash)
            with open(Path(result.out_dir) / "recipe.json", encoding="utf-8") as f:
                json.load(f)


if __name__ == "__main__":
    unittest.main()
