"""Apartment balconies and emergency stairs keep their intended walking route."""

import unittest
from pathlib import Path

from promodeler.build import load_asset


ROOT = Path(__file__).resolve().parent.parent


def bounds(part):
    center = part["transform"]["translation"]
    size = part["shape"]["size"]
    return tuple((c - s / 2, c + s / 2) for c, s in zip(center, size))


class ApartmentCirculationTests(unittest.TestCase):
    def test_balcony_end_walls_are_tiled(self):
        recipe = load_asset(str(ROOT / "assets" / "02-apartment.py")).recipe
        parts = {part["id"]: part for part in recipe["asset"]["parts"]}
        for side in ("w", "e"):
            wall = parts[f"site_standalone_balcony_end_{side}"]
            self.assertEqual(wall["material"], "tile")
            self.assertAlmostEqual(bounds(wall)[2][0], 7.0)
            self.assertAlmostEqual(bounds(wall)[2][1], 8.5)
        self.assertIn("tile", recipe["asset"]["extras"]["tiled_materials"])

    def test_rear_corridor_opens_to_two_stair_runs_and_landing(self):
        recipe = load_asset(str(ROOT / "assets" / "02-apartment.py")).recipe
        parts = {part["id"]: part for part in recipe["asset"]["parts"]}
        corridor = bounds(parts["site_standalone_corridors"])
        for side in ("w", "e"):
            tag = f"site_standalone_stair_{side}_"
            bridge = bounds(parts[tag + "corridor_bridge"])
            entry = bounds(parts[tag + "landings"])
            header = bounds(parts[tag + "back"])
            middle = bounds(parts[tag + "mid_landings"])
            first = bounds(parts[tag + "flight_a"])
            second = bounds(parts[tag + "flight_b"])
            self.assertAlmostEqual(corridor[0][0] if side == "w" else corridor[0][1],
                                   bridge[0][1] if side == "w" else bridge[0][0])
            self.assertAlmostEqual(corridor[2][0], bridge[2][0])
            self.assertAlmostEqual(corridor[2][1], bridge[2][1])
            self.assertAlmostEqual(bridge[2][1], entry[2][0])
            self.assertAlmostEqual(corridor[1][1], bridge[1][1])
            self.assertAlmostEqual(bridge[1][1], entry[1][1])
            self.assertGreater(header[1][0] - entry[1][1], 2.0)
            self.assertAlmostEqual(middle[2][1] - middle[2][0], 1.2)
            self.assertGreater(first[1][0], entry[1][1])
            self.assertAlmostEqual(middle[1][1], 1.7)
            self.assertGreater(second[1][0], middle[1][1])
            self.assertEqual(parts[tag + "outside"]["material"], "tile")
            self.assertEqual(parts[tag + "inside"]["material"], "tile")
            self.assertEqual(parts[tag + "waist_a_outer"]["shape"]["kind"], "extrude")
            self.assertEqual(parts[tag + "waist_b_inner"]["material"], "concrete")


if __name__ == "__main__":
    unittest.main()
