"""The convenience store remains walkable and its requested departments are stocked."""

import unittest
from pathlib import Path

from assets.city import city_tile_specs
from promodeler.build import load_asset


ROOT = Path(__file__).resolve().parent.parent


class ConvenienceMerchandisingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recipe = load_asset(str(ROOT / "assets" / "03-convenience.py")).recipe
        cls.open_pose = next(pose for pose in recipe["asset"]["poses"]
                             if pose["id"] == "open")
        cls.parts = {part["id"].removeprefix("site_standalone_"): part
                     for part in recipe["asset"]["parts"]}

    @staticmethod
    def bounds(part):
        center = part["transform"]["translation"]
        size = part["shape"]["size"]
        return tuple((value - extent / 2, value + extent / 2)
                     for value, extent in zip(center, size))

    def test_shelves_are_stocked_end_to_end_with_clear_aisles(self):
        for index, category in enumerate(("cup_noodles", "bread", "daily_goods")):
            board = self.parts[f"shelf_{index}_boards"]
            self.assertAlmostEqual(board["shape"]["size"][2], 3.6)
            self.assertEqual(board["modifiers"][0]["count"], 5)
            stocked = [part for name, part in self.parts.items()
                       if name.startswith(category + "_")]
            self.assertGreaterEqual(len(stocked), 10)
            for part in stocked:
                array = part["modifiers"][0]
                self.assertGreaterEqual(array["count"], 10)
                self.assertGreaterEqual(array["count"] * array["offset"][2], 3.4)
            side = self.parts[f"shelf_{index}_left"]
            self.assertLess(side["shape"]["size"][2], 0.1)
        self.assertAlmostEqual(
            self.parts["shelf_1_boards"]["transform"]["translation"][0]
            - self.parts["shelf_0_boards"]["transform"]["translation"][0], 3.0)

    def test_requested_departments_follow_the_plan(self):
        for category in ("magazine_covers", "printer_body"):
            self.assertTrue(any(name.startswith(category) and
                                part["transform"]["translation"][2] > 4
                                for name, part in self.parts.items()))
        for category in ("fresh", "dessert"):
            self.assertTrue(any(name.startswith(category) and
                                part["transform"]["translation"][2] < -2.0
                                for name, part in self.parts.items()))
        self.assertLess(self.parts["register_drawer"]["transform"]["translation"][0], -4)
        self.assertNotIn("cold_glass", self.parts)
        self.assertFalse(any(name.startswith("cold_door") for name in self.parts))
        self.assertIn("right_cooler_door_0", self.parts)
        self.assertIn("right_cooler_goods_0_0", self.parts)

    def test_automatic_entry_and_l_shaped_checkout(self):
        left = self.parts["entry_left"]
        right = self.parts["entry_right"]
        self.assertEqual(left["parent_joint"], "j_entry_left")
        self.assertEqual(right["parent_joint"], "j_entry_right")
        self.assertGreaterEqual(self.bounds(right)[0][0] - self.bounds(left)[0][1], 0.9 - 1e-6)
        self.assertIn("entry_sensor", self.parts)
        self.assertIn("entry_track", self.parts)
        self.assertAlmostEqual(self.open_pose["joints"]["j_entry_left"]["translation"][0], -0.45)
        self.assertAlmostEqual(self.open_pose["joints"]["j_entry_right"]["translation"][0], 0.45)
        long_leg = self.bounds(self.parts["checkout"])
        return_leg = self.bounds(self.parts["checkout_return"])
        self.assertGreater(long_leg[2][1] - long_leg[2][0], 3.6)
        self.assertGreater(return_leg[0][1] - return_leg[0][0], 3.5)
        self.assertEqual(self.parts["right_cooler_door_0"]["parent_joint"], "j_cooler")
        cooler_back = self.bounds(self.parts["right_cooler_back"])[0][1]
        inside_wall = self.bounds(self.parts["wall_e"])[0][0]
        self.assertLessEqual(inside_wall - cooler_back, 0.05 + 1e-6)

    def test_people_can_pass_between_central_shelves_and_cold_displays(self):
        rear_front = self.bounds(self.parts["cold_wall_base"])[2][1]
        center_back = self.bounds(self.parts["shelf_1_boards"])[2][0]
        self.assertGreaterEqual(center_back - rear_front, 1.2)
        center_front = self.bounds(self.parts["shelf_0_boards"])[2][1]
        checkout_back = self.bounds(self.parts["checkout_return"])[2][0]
        self.assertGreaterEqual(checkout_back - center_front, 1.2)
        right_face = self.bounds(self.parts["right_cooler_base"])[0][0]
        shelf_right = self.bounds(self.parts["shelf_2_boards"])[0][1]
        self.assertGreaterEqual(right_face - shelf_right, 1.2)

    def test_exterior_has_its_own_tile_pattern(self):
        for wall in ("wall_n", "wall_w", "wall_e", "roof_fascia"):
            self.assertEqual(self.parts[wall]["material"], "store_tile")
        spec = city_tile_specs()["store_tile"]
        self.assertEqual(spec["pattern"], "store_tile")
        self.assertGreater(spec["scale_m"], 0.095)


if __name__ == "__main__":
    unittest.main()
