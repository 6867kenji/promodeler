"""The host side of the Unity build, exercised against a fake Unity executable that writes build.json."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from promodeler.character import Catalog, CharacterRecipe, bridge
from promodeler.character.from_blueprint import character_from_blueprint, load_blueprint
from promodeler.core import ModelingError

ROOT = Path(__file__).resolve().parent.parent

FAKE_UNITY = r'''
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default
out = Path(opt("-out"))
recipe = json.loads(Path(opt("-recipe")).read_text(encoding="utf-8"))
mode = Path(__file__).with_name("mode.txt").read_text().strip()
if mode == "crash":
    sys.exit(1)
if mode == "license":
    print("No valid Unity Editor license found. Please activate your license.")
    sys.exit(198)
PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
renders = []
if "-nographics" not in args:
    (out / "renders").mkdir(exist_ok=True)
    for view in opt("-views").split(","):
        for pas in opt("-passes").split(","):
            path = out / "renders" / f"{view}_{pas}.png"
            path.write_bytes(PNG_1X1)
            renders.append({"view": view, "pass": pas, "path": str(path), "written": True, "seconds": 0.1})
build = {
    "status": "ok", "environment": {"unity": "6000.3.21f1", "hdrp": "17.3.0", "uma": "3.0.4"},
    "resolved": {"race": "HumanMale", "dna": {"height": 0.6}, "iterations": 3, "residuals_m": {"barefoot_height": 0.001}},
    "measured_m": {"barefoot_height": recipe["body"]["measurements_m"]["barefoot_height"] + 0.001, "chest": 0.97},
    "parts": {"body": {"triangles": 30000}}, "totals": {"triangles": 30000, "materials": 4},
    "wardrobe": [{"slot": g["slot"], "catalog_id": g["catalog_id"], "resolved": None, "fitted": g["catalog_id"] is not None} for g in recipe["wardrobe"]],
    "renders": renders,
    "exports": {fmt: {"path": str(out / f"model.{fmt}"), "written": True, "bytes": 10} for fmt in opt("-formats").split(",")},
    "warnings": [{"code": "resolve.residual", "message": "test"}], "seconds": 1.5,
}
(out / "build.json").write_text(json.dumps(build), encoding="utf-8")
'''


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = self.tmp / "unity"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
        (self.project / "Packages").mkdir()
        (self.project / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {"com.umasteeringgroup.uma": "file:../../uma"}}))
        (self.project / "Assets" / "ProModeler" / "Editor" / "Batch").mkdir(parents=True)
        (self.project / "Assets" / "ProModeler" / "Editor" / "Batch" / "CharacterBatchBuilder.cs").write_text("// stub")
        (self.project / "Assets" / "UMA" / "Core").mkdir(parents=True)
        (self.project / "Assets" / "UMA" / "package.json").write_text('{"name": "com.umasteeringgroup.uma", "version": "3.0.4"}')
        (self.tmp / "fake_unity.py").write_text(FAKE_UNITY, encoding="utf-8")
        (self.tmp / "mode.txt").write_text("ok")
        if os.name == "nt":
            self.unity = self.tmp / "Unity.cmd"
            self.unity.write_text(f'@"{sys.executable}" "{self.tmp / "fake_unity.py"}" %*\r\n')
        else:
            self.unity = self.tmp / "Unity"
            self.unity.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.tmp / "fake_unity.py"}" "$@"\n')
            self.unity.chmod(0o755)
        os.environ["PROMODELER_UNITY"] = str(self.unity)
        self.catalog = Catalog()
        blueprint = load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "27-karate-master" / "blueprint.json")
        self.recipe, _ = character_from_blueprint(blueprint, self.catalog)  # no accessories, but the belt is a garment prop
        # Garment props (the karate belt) would run Blender; stand in for the prop builder and keep its bookkeeping.
        self.built_requests = []

        def fake_build_props(requests, force, log=None):
            self.built_requests.extend(requests)
            return {r.id: {"glb": None, "hash": "fake" + r.id[-4:], "ok": True, "socket": {"socket": r.socket, "grip_offset_m": [0, 0.27, 0], "orientation": "follow_bone"},
                           "error": None, "catalog_id": r.catalog_id, "slot": r.slot, "parameters": r.overrides} for r in requests}

        patcher = mock.patch.object(bridge, "_build_props", fake_build_props)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        os.environ.pop("PROMODELER_UNITY", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_environment_detection(self):
        self.assertEqual(bridge.project_version(self.project), "6000.3.21f1")
        self.assertEqual(bridge.uma_version(self.project), "3.0.4")
        self.assertEqual(bridge.find_unity(self.project), str(self.unity))
        self.assertEqual(bridge.project_ready(self.project), (True, ""))
        self.assertFalse(bridge.project_ready(self.tmp / "nowhere")[0])

    def test_stage_writes_inputs_and_hash_is_stable(self):
        a = bridge.stage(self.recipe, None, self.catalog, out_root=self.tmp / "build", project=self.project)
        b = bridge.stage(self.recipe, None, self.catalog, out_root=self.tmp / "build", project=self.project)
        self.assertEqual(a.hash, b.hash)
        self.assertTrue(a.recipe_path.is_file())
        assets = json.loads((a.out_dir / "assets.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(a.recipe_path.read_text(encoding="utf-8"))["id"], "karate-master")
        # The belt garment is staged as a prop keyed by slot, with the catalog's socket and evaluated parameters.
        self.assertEqual(list(assets["garments"]), ["waist"])
        self.assertEqual(assets["garments"]["waist"]["catalog_id"], "karate_belt_01")
        self.assertEqual(assets["garments"]["waist"]["socket"]["socket"], "waist")
        self.assertEqual(assets["accessories"], {})
        self.assertEqual([r.id for r in self.built_requests[:1]], ["garment:waist"])

    def test_prop_requests_evaluate_catalog_parameters(self):
        requests = bridge.prop_requests(self.recipe, self.catalog)
        self.assertEqual([r.id for r in requests], ["garment:waist"])
        belt = requests[0]
        self.assertEqual(belt.path, "assets/props/obi_belt.py")
        waist = next(s for s in self.recipe.body.measurements_m.cross_sections if s.landmark == "waist")
        garment = next(g for g in self.recipe.wardrobe if g.slot == "waist")
        self.assertAlmostEqual(belt.overrides["size"][0], waist.width + 0.07)
        self.assertAlmostEqual(belt.overrides["size"][1], garment.finished_measurements_m["width"])
        self.assertAlmostEqual(belt.overrides["size"][2], waist.depth + 0.07)
        self.assertEqual(belt.overrides["color"], garment.material.base_color_srgb)
        # Expressions: numbers, garment and body references, sums; anything else is a catalog error.
        self.assertEqual(bridge.evaluate_parameter(0.5, garment, self.recipe), 0.5)
        self.assertEqual(bridge.evaluate_parameter("body.barefoot_height + 0.01", garment, self.recipe), self.recipe.body.measurements_m.barefoot_height + 0.01)
        self.assertEqual(bridge.evaluate_parameter("body.waist", garment, self.recipe), self.recipe.body.measurements_m.circumferences["waist"])
        with self.assertRaises(ModelingError) as ctx:
            bridge.evaluate_parameter("garment.sleeve", garment, self.recipe)
        self.assertEqual(ctx.exception.code, "catalog.parameters")
        with self.assertRaises(ModelingError):
            bridge.evaluate_parameter("garment.material.base_color_srgb + 1", garment, self.recipe)
        # A recipe without prop garments requests nothing from the catalog.
        self.assertEqual(bridge.prop_requests(self.recipe, None), [])

    def test_build_reads_build_json_and_caches(self):
        result = bridge.build(self.recipe, catalog=self.catalog, out_root=self.tmp / "build", project=self.project, views=("front", "side"), passes=("shaded",))
        self.assertTrue(result.ok, result.build)
        self.assertFalse(result.cached)
        self.assertEqual(result.build["recipe_hash"], result.hash)
        self.assertEqual(result.build["unity_exit_code"], 0)
        self.assertEqual(len(result.build["renders"]), 2)
        self.assertEqual(result.build["measured_m"]["barefoot_height"], 1.781)
        self.assertIn("wall_seconds", result.build)
        again = bridge.build(self.recipe, catalog=self.catalog, out_root=self.tmp / "build", project=self.project, views=("front", "side"), passes=("shaded",))
        self.assertTrue(again.cached)
        forced = bridge.build(self.recipe, catalog=self.catalog, out_root=self.tmp / "build", project=self.project, force=True, render=False)
        self.assertFalse(forced.cached)
        self.assertEqual(forced.build["renders"], [])

    def test_crash_and_license_are_reported_not_hidden(self):
        (self.tmp / "mode.txt").write_text("crash")
        result = bridge.build(self.recipe, catalog=self.catalog, out_root=self.tmp / "build", project=self.project)
        self.assertFalse(result.ok)
        self.assertEqual(result.build["error"]["code"], "unity.noReport")
        self.assertEqual(result.build["unity_exit_code"], 1)
        (self.tmp / "mode.txt").write_text("license")
        result = bridge.build(self.recipe, catalog=self.catalog, out_root=self.tmp / "build", project=self.project, force=True)
        self.assertEqual(result.build["error"]["code"], "unity.license")

    def test_cli_build_all_visits_every_recipe_once(self):
        from types import SimpleNamespace
        from promodeler.character import cli
        import io, contextlib

        saved = cli.bridge.UNITY_PROJECT
        cli.bridge.UNITY_PROJECT = self.project
        try:
            args = SimpleNamespace(all=True, target=None, outfit=None, out=str(self.tmp / "build"), force=False, views="front", passes="shaded",
                                   formats="fbx", no_render=False, verbose=False, probe=False)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.cmd_character_build(args)
        finally:
            cli.bridge.UNITY_PROJECT = saved
        text = out.getvalue()
        recipes = sorted(p.stem for p in cli.RECIPES_DIR.glob("*.json"))
        self.assertEqual(code, 0, text[-2000:])
        self.assertEqual(text.count("====="), 2 * len(recipes))  # one banner per recipe, not a recursion
        for recipe_id in recipes:
            self.assertTrue((self.tmp / "build" / recipe_id).is_dir(), recipe_id)

    def test_batch_command_shape(self):
        staged = bridge.stage(self.recipe, None, self.catalog, out_root=self.tmp / "build", project=self.project)
        command = bridge.batch_command("Unity.exe", staged, ("front",), ("shaded",), ("fbx",), render=False, project=self.project)
        self.assertEqual(command[:3], ["Unity.exe", "-nographics", "-batchmode"])
        self.assertIn("-executeMethod", command)
        self.assertEqual(command[command.index("-executeMethod") + 1], bridge.BATCH_METHOD)
        self.assertNotIn("-quit", command)  # the builder exits itself once UMA's asynchronous generation has finished


if __name__ == "__main__":
    unittest.main()
