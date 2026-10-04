"""The city keeps 64 designed sites and adds repeatable, collision-free infill."""

import copy
import unittest
from pathlib import Path
import math

from assets.city import CITY, _overlap, _variation, asset, city_layout, footprint, infill_sites, validate_city_layout
from assets.city_layout import validate_dense_layout
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
        self.assertEqual(len(loaded.recipe["blueprint"]["dependencies"]), 11)
        self.assertTrue(any(d["path"].endswith("density_layout.json")
                            for d in loaded.recipe["blueprint"]["dependencies"]))
        self.assertIn("site_b-0-0-0_stair_w_flight_a", ids)
        self.assertIn("site_b-0-0-1_checkout", ids)
        self.assertIn("site_b-0-0-2_stair_w_upper_a", ids)
        self.assertEqual(len(asset.generate().parts), len(ids))

    def test_infill_is_dense_varied_and_keeps_roads_clear(self):
        sites = infill_sites()
        self.assertEqual(sites, infill_sites())
        self.assertEqual(len(sites), 256)
        self.assertGreaterEqual(len({site["facade"] for site in sites}), 6)
        self.assertGreaterEqual(len({site["floors"] for site in sites}), 7)
        occupied = [tuple(zone["rect_xz_m"]) for zone in CITY["layout"]]
        layout = city_layout()
        for record in layout["buildings"]:
            if record["kind"] == "designed":
                occupied.append(tuple(record["bounds"]))
        occupied.extend(tuple(reserve["bounds"]) for reserve in layout["reservedSites"])
        for site in sites:
            bounds = site["bounds"]
            self.assertFalse(any(_overlap(bounds, other) for other in occupied), site["id"])
            occupied.append(bounds)

    def test_rooftop_equipment_stays_within_its_roof_and_height_limit(self):
        model = asset.generate()
        sites = {site["id"]: site for site in city_layout()["buildings"]}
        found = set()
        for part in model.parts:
            if "_roof_ac_" not in part.id:
                continue
            site_id = part.id.split("_roof_ac_", 1)[0]
            found.add(site_id)
            left, back, right, front = sites[site_id]["bounds"]
            x, y, z = part.transform.translation
            self.assertTrue(left < x < right and back < z < front, part.id)
            if part.id.endswith("_housing"):
                sx, sy, sz = part.shape.size
                yaw = part.transform.rotation[1]
                half_x = (abs(math.cos(yaw)) * sx + abs(math.sin(yaw)) * sz) * part.transform.scale[0] / 2
                half_z = (abs(math.sin(yaw)) * sx + abs(math.cos(yaw)) * sz) * part.transform.scale[2] / 2
                self.assertTrue(left <= x - half_x and x + half_x <= right, part.id)
                self.assertTrue(back <= z - half_z and z + half_z <= front, part.id)
                self.assertLess(y + sy * part.transform.scale[1] / 2, 40, part.id)
        self.assertEqual(found, set(sites))

    def test_twenty_per_block_close_frontages_and_narrow_building_gaps(self):
        layout = city_layout()
        self.assertEqual(layout, city_layout())
        for row in range(4):
            for column in range(4):
                self.assertEqual(sum(r["block"] == [column, row] for r in layout["buildings"]), 20)
        for record in layout["buildings"]:
            for gap in record["side_gaps_m"]:
                if gap is not None:
                    self.assertGreaterEqual(gap, 1)
                    self.assertLessEqual(gap, 12)
                    if record["width"] <= 14:
                        self.assertLessEqual(gap, 2.4)
        self.assertGreater(max(g["distance_m"] for g in layout["sideGaps"]), 8)
        self.assertEqual(layout["frontageSetbackM"], 1.4)
        # Top and bottom rows align to each block edge, rather than the
        # previous 20+ m setbacks; only the declared future sites interrupt.
        intervals = ((-250, -130), (-120, -10), (10, 120), (130, 250))
        for record in layout["buildings"]:
            _, block_row = record["block"]
            if record["row"] == 0:
                self.assertAlmostEqual(record["bounds"][1] - intervals[block_row][0], 1.4)
            elif record["row"] == 3:
                self.assertAlmostEqual(intervals[block_row][1] - record["bounds"][3], 1.4)

    def test_reservation_collisions_are_rejected(self):
        layout = copy.deepcopy(city_layout())
        reserve = layout["occupiedSites"][0]
        record = next(r for r in layout["buildings"] if r["block"] == reserve["block"])
        record["bounds"] = reserve["bounds"][:]
        layout["reservedSites"] = [reserve]
        with self.assertRaises(ModelingError):
            validate_dense_layout(layout, CITY)
        for reserve in city_layout()["occupiedSites"]:
            self.assertGreaterEqual(reserve["size_m"][0], 28)
            self.assertGreaterEqual(reserve["size_m"][1], 40)


if __name__ == "__main__":
    unittest.main()
