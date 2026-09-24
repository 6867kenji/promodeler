"""Station escalators, fare control and tactile guidance remain functional."""

import unittest
from pathlib import Path

from promodeler.build import load_asset


ROOT = Path(__file__).resolve().parent.parent


def recipe(folder):
    return load_asset(str(ROOT / "assets" / f"{folder}.py")).recipe


class SubwayAccessTests(unittest.TestCase):
    def test_entrance_escalators_have_treads_glass_and_rubber_handrails(self):
        asset = recipe("17-subway-entrance")["asset"]
        parts = {part["id"]: part for part in asset["parts"]}
        for direction in ("up", "down"):
            prefix = f"entry-es-{direction}"
            treads = [name for name in parts if name.startswith(prefix + "_step_1_")]
            self.assertGreaterEqual(len(treads), 25)
            for side in (-1, 1):
                glass = parts[f"{prefix}_glass_1_{side}"]
                handrail = parts[f"{prefix}_handrail_1_{side}"]
                self.assertEqual(glass["material"], "glass")
                self.assertEqual(handrail["material"], "rubber")
                self.assertGreater(abs(glass["transform"]["rotation"][0]), 0.4)
                self.assertGreater(glass["shape"]["size"][2], 10)
        tiles = asset["extras"]["tiled_materials"]
        self.assertEqual(tiles["floor-tile"]["pattern"], "subway_floor")
        self.assertEqual(tiles["floor-tile"]["scale_m"], 1.2)
        self.assertEqual(tiles["rubber"]["pattern"], "rubber")

    def test_concourse_gate_ends_are_enclosed(self):
        asset = recipe("18-subway-concourse")["asset"]
        parts = {part["id"]: part for part in asset["parts"]}
        self.assertIn("staff_glass_front_s", parts)
        self.assertIn("staff_glass_door", parts)
        self.assertIn("staff_shelf_0", parts)
        self.assertIn("staff_shelf_files_0_0", parts)
        self.assertIn("staff_chair_seat", parts)
        self.assertIn("fare_fence_post_21", parts)
        self.assertIn("gate_flap_edge_0", parts)
        self.assertIn("gate_status_7", parts)
        fence = parts["fare_fence_rail_1"]
        left = fence["transform"]["translation"][0] - fence["shape"]["size"][0] / 2
        right = fence["transform"]["translation"][0] + fence["shape"]["size"][0] / 2
        self.assertAlmostEqual(left, 3.81)
        self.assertAlmostEqual(right, 9.8)
        self.assertIn("bank-B-up_step_1_0", parts)

    def test_yellow_route_has_raised_ribs_and_warning_dots(self):
        asset = recipe("18-subway-concourse")["asset"]
        parts = {part["id"]: part for part in asset["parts"]}
        guide = parts["tactile_guide_-44"]
        rib = parts["tactile_rib_-44_0"]
        self.assertGreater(rib["transform"]["translation"][1],
                           guide["transform"]["translation"][1])
        for side in ("north", "south"):
            dots = parts[f"tactile_dots_{side}"]
            self.assertEqual(dots["shape"]["kind"], "cylinder")
            self.assertEqual([item["count"] for item in dots["modifiers"]], [6, 6])
        self.assertEqual(asset["extras"]["tiled_materials"]["floor-tile"]["scale_m"], 1.2)

    def test_platform_floor_matches_station_tiles(self):
        asset = recipe("19-subway-platform")["asset"]
        tiles = asset["extras"]["tiled_materials"]
        self.assertEqual(tiles["floor-tile"]["pattern"], "subway_floor")
        self.assertEqual(tiles["floor-tile"]["scale_m"], 1.2)
        self.assertEqual(tiles["floor-tile"]["resolution"], 1024)
        floor = next(part for part in asset["parts"] if part["id"] == "island-floor")
        self.assertEqual(floor["material"], "floor-tile")


if __name__ == "__main__":
    unittest.main()
