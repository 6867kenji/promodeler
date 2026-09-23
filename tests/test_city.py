"""The city layout has 64 legal sites and repeatable building geometry."""

import copy
import unittest
from pathlib import Path

from assets.city import CITY, asset, footprint, validate_city_layout
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


if __name__ == "__main__":
    unittest.main()
