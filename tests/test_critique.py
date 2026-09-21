"""Critique request construction, without network access."""

import json
import tempfile
import unittest
from pathlib import Path

from promodeler.critique import CRITIQUE_SCHEMA, build_messages, report_summary, select_images


class CritiqueTests(unittest.TestCase):
    def test_summary_strips_paths(self):
        report = {
            "asset": "Can", "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]},
            "parts": {"body": {"triangles": 10, "watertight": True, "volume": 0.1, "self_intersections": 0,
                               "non_manifold_edges": 0, "uv": {"coverage": 0.4},
                               "textures": {"base_color": {"path": "C:/secret/x.png", "resolution": 256}}}},
            "warnings": [{"code": "x", "message": "y"}],
        }
        summary = report_summary(report)
        self.assertEqual(summary["parts"]["body"]["textures"], {"base_color": 256})
        self.assertNotIn("path", json.dumps(summary))

    def test_messages_include_images_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "sheet.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            ref = Path(tmp) / "ref.jpg"
            ref.write_bytes(b"\xff\xd8\xff" + b"0" * 32)
            messages = build_messages([png], {"asset": "Can"}, "a rusty can", ref)
            content = messages[0]["content"]
            self.assertEqual([c["type"] for c in content], ["image", "image", "text"])
            self.assertEqual(content[0]["source"]["media_type"], "image/png")
            self.assertEqual(content[1]["source"]["media_type"], "image/jpeg")
            self.assertIn("reference photograph", content[2]["text"])
            self.assertIn("a rusty can", content[2]["text"])
        self.assertEqual(CRITIQUE_SCHEMA["required"], ["score", "verdict", "strengths", "issues", "next_steps"])

    def test_select_images_prefers_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "contact_sheet.png"
            sheet.write_bytes(b"x")
            report = {"contact_sheet": {"path": str(sheet)}, "renders": [{"path": "missing.png", "written": True}]}
            self.assertEqual(select_images(Path(tmp), report), [sheet])
            report = {"contact_sheet": None, "renders": [
                {"path": str(sheet), "written": True, "pass": "shaded"},
                {"path": str(sheet), "written": True, "pass": "clay"},
            ]}
            self.assertEqual(len(select_images(Path(tmp), report)), 1)


if __name__ == "__main__":
    unittest.main()
