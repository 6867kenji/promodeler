"""Garment generators cut on a race profile and the GLB -> UMA slot bridge (no Unity, no Blender)."""

import json
import unittest
from pathlib import Path
from unittest import mock

from promodeler.build import load_asset
from promodeler.character import bridge
from promodeler.core import ModelingError

ROOT = Path(__file__).resolve().parent.parent
SHIRT = str(ROOT / "assets" / "wardrobe" / "white_shirt.py")
PROFILE = ROOT / "character" / "profiles" / "human_female.json"


class WhiteShirtTests(unittest.TestCase):
    def test_profile_is_committed_and_well_formed(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["schema"], "promodeler-race-profile/1.0")
        self.assertEqual(profile["uma_race"], "Human Female 3.0")
        self.assertGreater(len(profile["torso_slices"]), 20)
        for side in ("left", "right"):
            arm = profile["arms"][side]
            self.assertIn("angle_z", arm)
            self.assertGreater(len(arm["slices"]), 10)
            self.assertEqual(len(arm["slices"][0]["center"]), 3)

    def test_shirt_builds_torso_and_two_sleeves_in_the_body_frame(self):
        loaded = load_asset(SHIRT)
        parts = {p["id"]: p for p in loaded.recipe["asset"]["parts"]}
        self.assertEqual(set(parts), {"torso", "sleeve_left", "sleeve_right"})
        torso = parts["torso"]["shape"]
        self.assertEqual(torso["kind"], "loft")
        self.assertFalse(torso["capped"])
        ys = [s["transform"]["translation"][1] for s in torso["sections"]]
        self.assertEqual(ys, sorted(ys))
        self.assertGreater(ys[0], 0.9)      # hem at the hip of the 1.99 m neutral body
        self.assertLess(ys[-1], 1.69)       # collar below the Neck bone
        counts = {len(s["points"]) for s in torso["sections"]}
        self.assertEqual(counts, {48})
        left = parts["sleeve_left"]["shape"]["sections"]
        right = parts["sleeve_right"]["shape"]["sections"]
        self.assertLess(left[1]["transform"]["translation"][0], 0.0)
        self.assertGreater(right[1]["transform"]["translation"][0], 0.0)
        self.assertAlmostEqual(left[1]["transform"]["rotation"][2], -right[1]["transform"]["rotation"][2], places=5)
        self.assertEqual(loaded.asset.extras["promodeler_garment"]["wardrobe_slot"], "TopUnderlayer")

    def test_shirt_parameters_are_checked(self):
        with self.assertRaises(ModelingError) as ctx:
            load_asset(SHIRT, parameter_overrides={"sleeve_length": 1.5})
        self.assertEqual(ctx.exception.code, "white_shirt.sleeve")
        with self.assertRaises(ModelingError) as ctx:
            load_asset(SHIRT, parameter_overrides={"profile": "character/profiles/nowhere.json"})
        self.assertEqual(ctx.exception.code, "garment.profile")
        short = load_asset(SHIRT, parameter_overrides={"sleeve_length": 0.3})
        long = load_asset(SHIRT, parameter_overrides={"sleeve_length": 0.9})
        sections = lambda l: len({p["id"]: p for p in l.recipe["asset"]["parts"]}["sleeve_left"]["shape"]["sections"])
        self.assertLess(sections(short), sections(long))


class SlotBridgeTests(unittest.TestCase):
    def test_wardrobe_slot_and_glb_are_validated_before_unity_runs(self):
        with self.assertRaises(ModelingError) as ctx:
            bridge.import_wardrobe_slot("nowhere.glb", "human_female", "x", "Torso")
        self.assertEqual(ctx.exception.code, "slot.wardrobeSlot")
        with self.assertRaises(ModelingError) as ctx:
            bridge.import_wardrobe_slot("nowhere.glb", "human_female", "x", "TopUnderlayer")
        self.assertEqual(ctx.exception.code, "slot.glb")

    def test_import_arguments_reach_the_editor_method(self):
        calls = []

        def fake_run(method, arguments, log_path, project, timeout, log=None, graphics=False):
            calls.append((method, list(arguments)))
            return 0

        with mock.patch.object(bridge, "_run_editor_method", fake_run):
            report = bridge.import_wardrobe_slot(SHIRT, "human_female", "unit_shirt", "TopUnderlayer", color="#FFFFFF",
                                                 material_from_recipe="colors_top_Recipe")
        self.assertEqual(calls[0][0], bridge.IMPORT_METHOD)
        args = calls[0][1]
        self.assertEqual(args[args.index("-wardrobe-slot") + 1], "TopUnderlayer")
        self.assertEqual(args[args.index("-material-from-recipe") + 1], "colors_top_Recipe")
        self.assertEqual(args[args.index("-out") + 1], "Assets/ProModeler/Generated/Wardrobe/unit_shirt")
        self.assertFalse(report["ok"])   # no import.json was written by the fake
        self.assertEqual(report["error"]["code"], "unity.noReport")


if __name__ == "__main__":
    unittest.main()
