import json
import os
import tempfile
import unittest

from promodeler.human import mhr


class HumanModuleTests(unittest.TestCase):
    def test_rig_from_file_keeps_ancestors(self):
        joints = [
            {"id": "root", "parent": None, "head": [0, 0.9, 0], "tail": [0, 0.95, 0]},
            {"id": "c_spine0", "parent": "root", "head": [0, 0.95, 0], "tail": [0, 1.05, 0]},
            {"id": "c_head", "parent": "c_spine0", "head": [0, 1.4, 0], "tail": [0, 1.5, 0]},
            {"id": "l_upleg", "parent": "root", "head": [0.08, 0.86, 0], "tail": [0.1, 0.5, 0]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rig.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"id": "mhr", "joints": joints}, f)
            rig = mhr.rig_from_file(path, rig_id="x", keep={"c_head"})
            rig.validate()
            self.assertEqual([j.id for j in rig.joints], ["root", "c_spine0", "c_head"])
            self.assertEqual(len(mhr.rig_from_file(path).joints), 4)
            lifted = mhr.rig_from_file(path, offset=(0.0, 0.025, 0.0))
            self.assertAlmostEqual(lifted.joints[0].head[1], 0.925)

    def test_blueprint_targets(self):
        blueprint = {"dimensions": {"barefoot_height_m": 1.6, "inseam_m": 0.735,
                                    "body_circumferences_m": {"bust": 0.9, "hip": 0.87}}}
        self.assertEqual(mhr.blueprint_targets(blueprint), {"height": 1.6, "inseam": 0.735, "bust": 0.9, "hip": 0.87})

    def test_parameter_names_follow_first_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.model")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[ParameterTransform]\nroot.tx = 1.0 * root_tx\nb.ry = 0.5 * scale_uplegs + 1.0 * b_ry  # c\n"
                        "limit root_tx minmax [0, 1]\nc.tx = 2.0 * root_tx\n")
            self.assertEqual(mhr.parameter_names(path), ["root_tx", "scale_uplegs", "b_ry"])

    @unittest.skipUnless(mhr.assets_available() and os.environ.get("PROMODELER_MHR_TESTS"), "MHR assets or torch not requested")
    def test_short_fit_moves_toward_targets(self):
        model = mhr.MHRModel()
        targets = {"height": 1.6, "shoulder_width": 0.36}
        body = model.fit(targets, iterations=40)
        self.assertLess(abs(body.measurements["height"] - 1.6), 0.03)
        self.assertAlmostEqual(float(body.vertices[:, 1].min()), 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
