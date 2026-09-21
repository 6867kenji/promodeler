"""Integration tests: run the real headless Blender kernel. Skipped when Blender is unavailable."""

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


def read_glb_json(path: str) -> dict:
    with open(path, "rb") as f:
        magic, version, _ = struct.unpack("<4sII", f.read(12))
        assert magic == b"glTF" and version == 2
        length, _ = struct.unpack("<II", f.read(8))
        return json.loads(f.read(length))


@unittest.skipUnless(blender_available(), "Blender not available")
class BuildTests(unittest.TestCase):
    def assert_clean(self, report: dict):
        for part_id, stats in report["parts"].items():
            self.assertTrue(stats["watertight"], f"{part_id} not watertight: {stats}")
            self.assertEqual(stats["self_intersections"], 0, part_id)
            self.assertEqual(stats["inconsistent_winding_edges"], 0, part_id)
            self.assertGreater(stats["volume"], 0.0, part_id)
        self.assertTrue(all(r["written"] for r in report["renders"]))
        self.assertTrue(report["export"]["written"])

    def test_crate_builds_renders_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(str(ROOT / "assets" / "crate.py"), out_root=tmp, force=True)
            self.assertTrue(result.ok, result.report.get("error"))
            report = result.report
            self.assertEqual(set(report["parts"]), {"body", "handle"})
            self.assert_clean(report)
            # Authoring space is Y up: the crate rests on y = 0 and its handle rises above it.
            self.assertAlmostEqual(report["bounds"]["min"][1], 0.0, places=3)
            self.assertGreater(report["bounds"]["max"][1], 0.5)
            gltf = read_glb_json(report["export"]["path"])
            self.assertEqual({n["name"] for n in gltf["nodes"]}, {"root", "body", "handle"})
            self.assertEqual({m["name"] for m in gltf["meshes"]}, {"mesh:body", "mesh:handle"})
            # Second build hits the cache.
            again = build(str(ROOT / "assets" / "crate.py"), out_root=tmp)
            self.assertTrue(again.cached)
            self.assertEqual(again.hash, result.hash)

    def test_mug_union_is_one_watertight_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(str(ROOT / "assets" / "mug.py"), out_root=tmp, force=True)
            self.assertTrue(result.ok, result.report.get("error"))
            self.assert_clean(result.report)
            body = result.report["parts"]["body"]
            # A closed hollow mug of 4 cm radius holds roughly a few hundred milliliters of material volume.
            self.assertLess(body["volume"], 0.0006)
            self.assertGreater(body["volume"], 0.00002)
            gltf = read_glb_json(result.report["export"]["path"])
            self.assertNotIn("cutter:body:0", {n["name"] for n in gltf["nodes"]})

    def test_wrench_hole_bevel_and_grooves(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(str(ROOT / "assets" / "wrench.py"), out_root=tmp, force=True)
            self.assertTrue(result.ok, result.report.get("error"))
            self.assert_clean(result.report)
            bounds = result.report["bounds"]
            extent = bounds["max"][0] - bounds["min"][0]
            # Jaw tips are trimmed by the head arc, so the extent is slightly under the nominal length.
            self.assertTrue(0.17 < extent <= 0.18, extent)
            self.assertAlmostEqual(bounds["min"][1], 0.0, places=4)
            self.assertAlmostEqual(bounds["max"][1], 0.006, places=4)

    def test_rusty_can_bakes_texture_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build(str(ROOT / "assets" / "rusty_can.py"), out_root=tmp, force=True,
                           quality_overrides={"texture_resolution": 128, "bake_samples": 2})
            self.assertTrue(result.ok, result.report.get("error"))
            self.assert_clean(result.report)
            body = result.report["parts"]["body"]
            self.assertEqual(set(body["textures"]), {"base_color", "roughness", "metallic", "normal"})
            for meta in body["textures"].values():
                self.assertTrue(os.path.isfile(meta["path"]), meta["path"])
                self.assertEqual(meta["resolution"], 128)
            self.assertGreater(body["uv"]["coverage"], 0.2)
            self.assertGreater(body["uv"]["texel_density_px_per_m"], 100)
            gltf = read_glb_json(result.report["export"]["path"])
            self.assertGreaterEqual(len(gltf.get("images", [])), 3)
            self.assertIn("normalTexture", gltf["materials"][0])
            self.assertIn("baseColorTexture", gltf["materials"][0]["pbrMetallicRoughness"])
            # Passes render every view; the contact sheet tiles them (when Pillow is installed).
            renders = result.report["renders"]
            self.assertEqual(len(renders), 2 * 3)
            self.assertEqual({r["pass"] for r in renders}, {"shaded", "clay", "wireframe"})
            sheet = result.report.get("contact_sheet")
            if sheet is not None:
                self.assertTrue(os.path.isfile(sheet["path"]))
                self.assertEqual(sheet["passes"], ["shaded", "clay", "wireframe"])
            # Displacement moved the wall: the can is no longer a perfect body of revolution.
            body = result.report["parts"]["body"]
            self.assertGreater(body["triangles"], 8000)


if __name__ == "__main__":
    unittest.main()
