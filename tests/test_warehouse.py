"""Access and roof openings must survive procedural warehouse placement."""

import copy
import math
import unittest

from assets.city import city_layout, asset
from assets.city_facilities import validate_facilities
from assets.warehouse import warehouse_parts
from promodeler.core import ModelingError


class WarehouseTests(unittest.TestCase):
    def test_centre_bay_has_no_wall_or_closed_shutter_across_its_opening(self):
        parts = warehouse_parts()
        # Sample the full opening, including a 1.8 m human route and cargo
        # height, against actual primitive bounds rather than an ID count.
        for x in (-2.15, 0, 2.15):
            for y in (.25, 2., 4.5):
                for p in parts:
                    if p.shape.kind != "box" or any(p.transform.rotation):
                        continue
                    c, s = p.transform.translation, p.shape.size
                    self.assertFalse(all(abs(a-b) < size/2 for a, b, size in zip((x, y, 12.65), c, s)), p.id)

    def test_glazing_is_not_covered_by_an_opaque_roof(self):
        parts = warehouse_parts()
        glass = [p for p in parts if "_skylight_" in p.id and p.material == "wh_glass"]
        self.assertEqual(len(glass), 12)
        for pane in glass:
            gx, gy, gz = pane.transform.translation
            for panel in (p for p in parts if p.material == "wh_roof"):
                x, y, z = panel.transform.translation
                angle = panel.transform.rotation[2]
                projected_width = panel.shape.size[0]*abs(math.cos(angle))
                self.assertFalse(abs(gx-x) < projected_width/2 and abs(gz-z) < panel.shape.size[2]/2, panel.id)

    def test_north_placement_rotates_roof_slopes_with_the_shell(self):
        south, north = warehouse_parts(), warehouse_parts(origin=(26, 0, 46), yaw=math.pi)
        for original, placed in zip(south, north):
            x, y, z = original.transform.translation
            px, py, pz = placed.transform.translation
            self.assertAlmostEqual(px, 26-x)
            self.assertAlmostEqual(py, y)
            self.assertAlmostEqual(pz, 46-z)
            # At yaw pi, Ry(pi)*Rz(a) = Rz(-a)*Ry(pi).
            self.assertAlmostEqual(placed.transform.rotation[2], -original.transform.rotation[2])

    def test_city_keeps_base_density_and_connects_warehouse_access(self):
        layout = city_layout()
        self.assertEqual(len(layout["buildings"]), 320)
        self.assertEqual(layout["buildingCount"], 321)
        self.assertEqual(layout["reservedSites"], [])
        self.assertIn("future-station",[r["id"] for r in layout["occupiedSites"]])
        validate_facilities(layout)
        broken = copy.deepcopy(layout)
        broken["facilities"][0]["bounds"][2] = 50
        with self.assertRaisesRegex(ModelingError, "beyond"):
            validate_facilities(broken)
        broken = copy.deepcopy(layout)
        broken["facilities"][0]["pedestrianRoute"][1][1] += 2
        with self.assertRaisesRegex(ModelingError, "Disconnected|city.facilityWalkDisconnected"):
            validate_facilities(broken)
        parts = {p.id: p for p in asset.generate().parts}
        self.assertNotIn("curb_ew_1_2_1", parts)
        self.assertIn("lot_warehouse_drive_ramp_street", parts)
        # The doorway path is separate from the truck entrance, so bollards
        # and parking markings cannot block pedestrian movement.
        route = layout["facilities"][0]["pedestrianRoute"]
        for part in (p for p in parts.values() if p.id.startswith("facility_warehouse_") and "bollard" in p.id):
            x, y, z = part.transform.translation
            self.assertFalse(any(a < x < c and b < z < d for a, b, c, d in route))


if __name__ == "__main__":
    unittest.main()
