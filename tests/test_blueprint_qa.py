"""The design check must catch drift that a successful mesh build cannot see."""

import unittest
from pathlib import Path

from promodeler.blueprint_qa import check_blueprint
from promodeler.build import load_asset


ROOT = Path(__file__).resolve().parent.parent


class BlueprintQATests(unittest.TestCase):
    def setUp(self):
        self.blueprint = {
            "id": "sample", "dimensions": {"envelope_xyz_m": [1.0, 1.0, 1.0]},
            "target": {"triangles_lod0_max": 100, "texel_density_px_per_m": 512},
            "materials": [{"id": "paint"}],
            "parts": [{"id": "cabinet", "center_m": [0.0, 0.5, 0.0], "size_m": [1.0, 1.0, 1.0],
                       "material": "paint"}],
            "motions": [{"id": "door", "pivot_m": [-0.5, 0.0, 0.5]}],
        }
        self.recipe = {"asset": {
            "materials": [{"id": "paint"}],
            "parts": [{"id": "cabinet_body", "material": "paint"}],
            "rig": {"joints": [{"id": "j_door", "head": [-0.5, 0.0, 0.5]}]},
        }}
        self.report = {
            "bounds": {"min": [-0.5, 0.0, -0.5], "max": [0.5, 1.0, 0.5]},
            "totals": {"triangles": 12},
            "parts": {"cabinet_body": {
                "bounds": {"min": [-0.5, 0.0, -0.5], "max": [0.5, 1.0, 0.5]},
                "uv": {"texel_density_px_per_m": 600.0},
            }},
        }

    def test_matching_blueprint_passes(self):
        result = check_blueprint(self.blueprint, self.recipe, self.report,
                                 motion_map={"door": "j_door"}, required_parts=("cabinet_body",))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["issues"], [])

    def test_missing_detail_and_low_density_are_visible(self):
        self.report["parts"]["cabinet_body"]["uv"]["texel_density_px_per_m"] = 100.0
        result = check_blueprint(self.blueprint, self.recipe, self.report,
                                 motion_map={"door": "j_door"}, required_parts=("cabinet_handle",))
        self.assertEqual(result["status"], "needs_work")
        self.assertEqual({issue["code"] for issue in result["issues"]},
                         {"blueprint.detail", "blueprint.texelDensity"})

    def test_part_and_pivot_drift_are_errors(self):
        self.report["parts"]["cabinet_body"]["bounds"]["max"][0] = 0.6
        self.recipe["asset"]["rig"]["joints"][0]["head"][0] = -0.3
        result = check_blueprint(self.blueprint, self.recipe, self.report, motion_map={"door": "j_door"})
        self.assertEqual({issue["code"] for issue in result["issues"]},
                         {"blueprint.partBounds", "blueprint.motionPivot"})

    def test_motion_range_and_texture_budget(self):
        self.blueprint["target"]["texture_resolution_max"] = 1024
        self.blueprint["motions"][0].update({"range": [0, 90], "unit": "degree", "axis": [0, 1, 0]})
        self.recipe["asset"]["parts"][0]["texture_resolution"] = 2048
        self.recipe["asset"]["poses"] = [{"id": "open", "joints": {
            "j_door": {"rotation": [0.0, 0.5, 0.0], "translation": [0.0, 0.0, 0.0]},
        }}]
        result = check_blueprint(self.blueprint, self.recipe, self.report, motion_map={"door": "j_door"})
        self.assertEqual({issue["code"] for issue in result["issues"]},
                         {"blueprint.motionRange", "blueprint.textureBudget"})

    def test_missing_open_pose_is_visible(self):
        self.blueprint["motions"][0].update({"range": [0, 90], "unit": "degree", "axis": [0, 1, 0]})
        result = check_blueprint(self.blueprint, self.recipe, self.report, motion_map={"door": "j_door"})
        self.assertEqual({issue["code"] for issue in result["issues"]}, {"blueprint.motionPose"})

    def test_negative_only_motion_uses_its_nonzero_endpoint(self):
        self.blueprint["motions"][0].update({"range": [-0.6, 0], "unit": "m", "axis": [1, 0, 0]})
        self.recipe["asset"]["poses"] = [{"id": "open", "joints": {
            "j_door": {"rotation": [0.0, 0.0, 0.0], "translation": [-0.6, 0.0, 0.0]},
        }}]
        result = check_blueprint(self.blueprint, self.recipe, self.report, motion_map={"door": "j_door"})
        self.assertEqual(result["issues"], [])

    def test_scheduled_envelope_resolves_conflicting_summary_dimension(self):
        self.blueprint["dimensions"]["envelope_xyz_m"] = [1.0, 0.8, 1.0]
        result = check_blueprint(self.blueprint, self.recipe, self.report,
                                 motion_map={"door": "j_door"}, envelope_mode="scheduled")
        self.assertEqual(result["issues"], [])

    def test_environment_envelope_is_a_limit_and_prototype_has_local_size(self):
        self.blueprint["dimensions"]["envelope_xyz_m"] = [1, 3, 1]
        self.blueprint["parts"][0]["center_m"] = [25, 25, 25]
        result = check_blueprint(self.blueprint, self.recipe, self.report,
                                 motion_map={"door": "j_door"}, envelope_mode="height_maximum",
                                 prototype_parts=("cabinet",))
        self.assertEqual(result["issues"], [])

    def test_room_blueprint_and_texture_override_enter_recipe(self):
        path = str(ROOT / "assets" / "room.py")
        normal = load_asset(path)
        quick = load_asset(path, quality_overrides={"texture_resolution": 256})
        self.assertEqual(normal.recipe["blueprint"]["id"], "room")
        normal_floor = next(part for part in normal.recipe["asset"]["parts"] if part["id"] == "floor_living")
        quick_floor = next(part for part in quick.recipe["asset"]["parts"] if part["id"] == "floor_living")
        self.assertEqual(normal_floor["texture_resolution"], 4096)
        self.assertEqual(quick_floor["texture_resolution"], 256)


if __name__ == "__main__":
    unittest.main()
