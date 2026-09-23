"""Accessory assets validate without Blender, accept the recipe's size override and declare a socket."""

import glob
import unittest
from pathlib import Path

from promodeler.build import load_asset
from promodeler.core import ModelingError

ROOT = Path(__file__).resolve().parent.parent
PROPS = sorted(glob.glob(str(ROOT / "assets" / "props" / "*.py")))


class PropsTests(unittest.TestCase):
    def test_every_prop_validates_and_declares_a_socket(self):
        self.assertGreaterEqual(len(PROPS), 13)
        for path in PROPS:
            loaded = load_asset(path)
            extras = loaded.asset.extras or {}
            self.assertIn("promodeler_socket", extras, path)
            socket = extras["promodeler_socket"]
            self.assertIn(socket["socket"], ("hand_l", "hand_r", "wrist_l", "wrist_r", "shoulder_l", "shoulder_r", "back", "waist", "neck", "head", "face", "chest"), path)
            self.assertEqual(len(socket["grip_offset_m"]), 3, path)
            self.assertIn(socket["orientation"], ("world_up", "follow_bone"), path)
            self.assertTrue(all(m.base_color is not None for m in loaded.asset.materials), path)

    def test_size_override_changes_the_recipe(self):
        path = str(ROOT / "assets" / "props" / "tote.py")
        default = load_asset(path)
        resized = load_asset(path, parameter_overrides={"size": (0.28, 0.27, 0.10)})
        self.assertNotEqual(default.recipe["input"]["parameters"]["size"], resized.recipe["input"]["parameters"]["size"])
        self.assertEqual(resized.recipe["input"]["parameters"]["size"], [0.28, 0.27, 0.10])
        with self.assertRaises(ModelingError) as ctx:
            load_asset(path, parameter_overrides={"colour": "red"})
        self.assertEqual(ctx.exception.code, "generator.parameters")


if __name__ == "__main__":
    unittest.main()
