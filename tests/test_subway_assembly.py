"""Port coordinates, staircase landings and the street excavation agree."""

import unittest
from assets.subway_station import station,connections
from assets.city import city_layout,asset
from promodeler.core.profile import point_in_ring


class SubwayAssemblyTests(unittest.TestCase):
    def test_four_connections_share_positions_and_clearances(self):
        links=connections((-26,.15,15))
        self.assertEqual(len(links),4)
        self.assertEqual(links[0]["floor_center_world_m"],[-24,-5.85,-33])
        self.assertEqual(links[1]["floor_center_world_m"],[-26,-11.85,15])
        self.assertEqual(links[2]["floor_center_world_m"],[-26,-11.85,35])

    def test_openings_are_in_real_floor_and_ceiling_geometry(self):
        parts={p.id:p for p in station().parts}
        floor,ceiling=parts["station_c_floor"],parts["station_p_ceiling"]
        for surface in (floor,ceiling):
            self.assertEqual(surface.shape.kind,"extrude")
            self.assertEqual(len(surface.shape.profile.holes),3)
            self.assertTrue(any(point_in_ring((-1.9,8),h) for h in surface.shape.profile.holes))
        self.assertIn("station_e_entry-stair_landing_2",parts)
        self.assertIn("station_c_bank_A_bottom_link",parts)
        self.assertNotIn("station_e_closure_shutter",parts)

    def test_city_ground_is_open_above_the_stairs(self):
        layout=city_layout()
        self.assertEqual(layout["buildingCount"],321)
        subway=next(f for f in layout["facilities"] if f.get("kind")=="subway")
        self.assertFalse(subway["countAsBuilding"])
        parts={p.id:p for p in asset.generate().parts}
        for pid in ("ground","block_1_1"):
            self.assertTrue(any(point_in_ring((-28.1,52.),h) for h in parts[pid].shape.profile.holes))
            self.assertFalse(any(point_in_ring((-28.1,48.),h) for h in parts[pid].shape.profile.holes))
        self.assertIn("lot_subway_walk_0",parts)
        self.assertIn("facility_subway_entry_p_island-floor",parts)

    def test_lights_and_gate_readers_do_not_block_the_route(self):
        parts={p.id:p for p in station().parts}
        self.assertLess(parts["station_p_light_-12"].transform.translation[0],-3)
        self.assertGreater(parts["station_p_light_-12_east"].transform.translation[0],3)
        self.assertLess(parts["station_c_gate_reader_7"].transform.translation[0],2.63)


if __name__=="__main__":
    unittest.main()
