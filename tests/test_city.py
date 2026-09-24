"""The city keeps 64 designed sites and adds repeatable, collision-free infill."""

import copy
import unittest
from pathlib import Path

from assets.city import CITY, _overlap, _variation, asset, footprint, infill_sites, validate_city_layout
from promodeler.build import load_asset
from promodeler.core import ModelingError


ROOT = Path(__file__).resolve().parent.parent


class CityTests(unittest.TestCase):
    def test_blueprint_sites_fit_the_roads(self):
        validate_city_layout()
        self.assertEqual(len(CITY["placements"]), 64)
        self.assertEqual({item["blueprint"] for item in CITY["placements"]},
                         {"02-apartment", "03-convenience", "04-office"})

    def test_road_and_building_collisions_are_rejected(self):
        design = copy.deepcopy(CITY)
        design["placements"][0]["position_m"][0] = -125
        with self.assertRaisesRegex(ModelingError, "overlaps a designed road"):
            validate_city_layout(design)
        design = copy.deepcopy(CITY)
        design["placements"][1]["position_m"] = list(design["placements"][0]["position_m"])
        with self.assertRaisesRegex(ModelingError, "overlaps another building"):
            validate_city_layout(design)

    def test_recipe_contains_all_sites_and_design_dependencies(self):
        loaded = load_asset(str(ROOT / "assets" / "city.py"))
        ids = {part["id"] for part in loaded.recipe["asset"]["parts"]}
        for placement in CITY["placements"]:
            self.assertIn(f"site_{placement['id']}_foundation", ids)
            bounds = footprint(placement)
            self.assertGreater(bounds[2] - bounds[0], 0)
        self.assertEqual(loaded.recipe["blueprint"]["id"], "city")
        self.assertEqual(len(loaded.recipe["blueprint"]["dependencies"]), 3)
        self.assertIn("site_b-0-0-0_stair_w_flight_a", ids)
        self.assertIn("site_b-0-0-1_checkout", ids)
        self.assertIn("site_b-0-0-2_stair_w_upper_a", ids)
        self.assertEqual(len(asset.generate().parts), len(ids))

    def test_infill_is_dense_varied_and_keeps_roads_clear(self):
        sites = infill_sites()
        self.assertEqual(sites, infill_sites())
        self.assertEqual(len(sites), 80)
        self.assertGreaterEqual(len({site["facade"] for site in sites}), 6)
        self.assertGreaterEqual(len({site["floors"] for site in sites}), 7)
        occupied = [tuple(zone["rect_xz_m"]) for zone in CITY["layout"]]
        for index, placement in enumerate(CITY["placements"]):
            x, _, z = placement["position_m"]
            scale, _ = _variation(index)
            left, back, right, front = footprint(placement)
            occupied.append((x + (left - x) * scale, z + (back - z) * scale,
                             x + (right - x) * scale, z + (front - z) * scale))
        for site in sites:
            bounds = site["bounds"]
            self.assertFalse(any(_overlap(bounds, other) for other in occupied), site["id"])
            occupied.append(bounds)


if __name__ == "__main__":
    unittest.main()
