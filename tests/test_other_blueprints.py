"""Every non-character design has a loadable and budgeted generator."""

import json
import unittest
from pathlib import Path

from promodeler.build import load_asset


ROOT = Path(__file__).resolve().parent.parent
DESIGNS = ROOT / "blueprints" / "japan-realistic-v1"
FOLDERS = [f"{number:02d}-{name}" for number, name in (
    (2, "apartment"), (3, "convenience"), (4, "office"),
    (7, "bed"), (8, "sofa"), (9, "ceiling-light"), (10, "table-chair"),
    (11, "pc-desk"), (12, "pc-set"), (13, "refrigerator"),
    (14, "microwave"), (15, "gaming-pc-white"), (16, "gaming-pc-pink"),
    (17, "subway-entrance"), (18, "subway-concourse"),
    (19, "subway-platform"), (20, "cafe"), (21, "karate-dojo"),
)]


class OtherBlueprintTests(unittest.TestCase):
    def test_every_design_loads_with_parts_materials_and_texture_budget(self):
        for folder in FOLDERS:
            with self.subTest(folder=folder):
                blueprint = json.loads((DESIGNS / folder / "blueprint.json").read_text(encoding="utf-8"))
                loaded = load_asset(str(ROOT / "assets" / f"{folder}.py"))
                recipe = loaded.recipe
                self.assertEqual(recipe["blueprint"]["id"], blueprint["id"])
                parts = {part["id"]: part for part in recipe["asset"]["parts"]}
                materials = {material["id"] for material in recipe["asset"]["materials"]}
                limit = blueprint["target"]["texture_resolution_max"]
                for part in recipe["asset"]["parts"]:
                    self.assertIn(part["material"], materials)
                    self.assertLessEqual(part.get("texture_resolution") or 1024, limit)
                for expected in blueprint["parts"]:
                    mapped = loaded.blueprint_part_map.get(expected["id"], (expected["id"],))
                    self.assertTrue(all(part_id in parts for part_id in mapped), expected["id"])


if __name__ == "__main__":
    unittest.main()
