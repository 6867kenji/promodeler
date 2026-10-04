"""The authored-base mode stays independent of the existing UMA recipes."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from promodeler.build import BlenderNotFound, find_blender
from promodeler.character import CharacterRecipe, canonical
from promodeler.cli import main
from promodeler.core import ModelingError


ROOT = Path(__file__).resolve().parent.parent


class CanonicalRecipeTests(unittest.TestCase):
    def test_inspection_distinguishes_empty_groups_from_skin_weights(self):
        try:
            blender = find_blender()
        except BlenderNotFound:
            self.skipTest("Blender is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "binding_fixture.py"
            script.write_text("""
import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
data = bpy.data.armatures.new('Skeleton')
rig = bpy.data.objects.new('Rig', data)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone = data.edit_bones.new('DEF-body')
bone.head = (0, 0, -1)
bone.tail = (0, 0, 1)
bpy.ops.object.mode_set(mode='OBJECT')
for name, count in [('EmptyGroups', 0), ('Weighted', 8), ('Partial', 4), ('Envelopes', 0)]:
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = name
    group = obj.vertex_groups.new(name='DEF-body')
    if count:
        group.add(list(range(count)), 1., 'REPLACE')
    mod = obj.modifiers.new('Armature', 'ARMATURE')
    mod.object = rig
    if name == 'Envelopes':
        mod.use_vertex_groups = False
        mod.use_bone_envelopes = True
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
""", encoding="utf-8")
            source = root / "binding.blend"
            result = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "23",
                                     "--python", str(script), "--", str(source)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            inventory = canonical.inspect_base(source, root / "inventory.json")
            meshes = {obj["name"]: obj for obj in inventory["objects"] if obj["type"] == "MESH"}
            self.assertTrue(meshes["EmptyGroups"]["skinned"])
            self.assertEqual(meshes["EmptyGroups"]["bindingStatus"], "empty_weights")
            self.assertEqual(meshes["EmptyGroups"]["weightedVertices"], 0)
            self.assertEqual(meshes["Weighted"]["bindingStatus"], "complete")
            self.assertEqual(meshes["Weighted"]["weightedVertices"], 8)
            self.assertEqual(meshes["Partial"]["weightCoverage"], .5)
            self.assertEqual(meshes["Envelopes"]["bindingStatus"], "envelope_binding")
            self.assertEqual({issue["mesh"] for issue in inventory["bindingIssues"]}, {"EmptyGroups", "Partial"})

    def test_fbx_base_manifest_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "base.Fbx").write_bytes(b"Kaydara FBX Binary")
            manifest = {"id": "RiggedWoman_v1", "model": "base.Fbx",
                        "parameters": {"body.armLength": {"bones": [
                            {"name": "Upperarm_L", "axis": "Y", "scale": [0.92, 1.08]}]}}}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded, model = canonical.load_manifest(path)
            self.assertEqual(loaded, manifest)
            self.assertEqual(model, root / "base.Fbx")

    def test_uma_recipe_can_be_migrated_without_modifying_it(self):
        source = json.loads((ROOT / "character/recipes/woman.json").read_text(encoding="utf-8"))
        legacy = CharacterRecipe.from_json(source)
        recipe = canonical.from_uma(legacy)
        self.assertEqual(recipe["schema"], canonical.SCHEMA)
        self.assertEqual(recipe["base"], "SemiRealBase_Female_v1")
        self.assertEqual(recipe["appearance"]["hairStyle"], "hair_long_straight_01")
        self.assertEqual(legacy.to_json(), source)
        canonical.validate(recipe)

    def test_invalid_sliders_and_unmapped_choices_are_reported(self):
        recipe = {"schema": canonical.SCHEMA, "id": "sample", "name": "Sample",
                  "base": "Base_v1", "seed": 1, "face": {"jawWidth": 0.8},
                  "body": {}, "appearance": {"hairStyle": "hair_a"},
                  "material": {"skinTone": "#DEC6B2"}, "wardrobe": {}}
        canonical.validate(recipe)
        self.assertEqual(canonical.compatibility(recipe, {"id": "Base_v1"}),
                         ["face.jawWidth", "appearance.hairStyle=hair_a", "material.skinTone"])
        recipe["face"]["jawWidth"] = 1.1
        with self.assertRaises(ModelingError):
            canonical.validate(recipe)
        recipe["face"]["jawWidth"] = 0.8
        recipe["underwear"] = {"top": False, "bottom": True}
        canonical.validate(recipe)
        recipe["underwear"]["top"] = 0
        with self.assertRaises(ModelingError):
            canonical.validate(recipe)

    def test_cli_keeps_uma_default_and_writes_canonical_on_request(self):
        blueprint = str(ROOT / "blueprints/japan-realistic-v1/05-woman/blueprint.json")
        with tempfile.TemporaryDirectory() as temp:
            uma = Path(temp) / "uma.json"
            new = Path(temp) / "canonical.json"
            self.assertEqual(main(["character", "recipe", blueprint, "--out", str(uma)]), 0)
            self.assertEqual(main(["character", "recipe", blueprint, "--mode", "canonical",
                                   "--out", str(new)]), 0)
            self.assertEqual(json.loads(uma.read_text(encoding="utf-8"))["schema"], "promodeler-character/1.0")
            self.assertEqual(json.loads(new.read_text(encoding="utf-8"))["schema"], canonical.SCHEMA)
            routed = Path(temp) / "routed.json"
            self.assertEqual(main(["generate", blueprint, "--mode", "canonical", "--no-build",
                                   "--out", str(routed)]), 0)
            self.assertEqual(json.loads(routed.read_text(encoding="utf-8"))["schema"], canonical.SCHEMA)

    def test_random_and_prompt_can_emit_canonical_recipes(self):
        with tempfile.TemporaryDirectory() as temp:
            random_dir = Path(temp) / "random"
            self.assertEqual(main(["character", "random", "--mode", "canonical", "--count", "1",
                                   "--seed", "123", "--out", str(random_dir)]), 0)
            random_recipe = next(random_dir.glob("*.json"))
            self.assertEqual(json.loads(random_recipe.read_text(encoding="utf-8"))["schema"], canonical.SCHEMA)
            prompted = Path(temp) / "prompt.json"
            self.assertEqual(main(["character", "prompt", "20代の女性、黒髪でカジュアル",
                                   "--mode", "canonical", "--out", str(prompted)]), 0)
            self.assertEqual(json.loads(prompted.read_text(encoding="utf-8"))["schema"], canonical.SCHEMA)

    def test_glb_compiler_applies_shape_key_and_module_selection(self):
        try:
            blender = find_blender()
        except BlenderNotFound:
            self.skipTest("Blender is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "fixture.py"
            script.write_text("""
import bpy
import sys
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(size=1)
obj=bpy.context.object
obj.name='Body'
coverage=obj.vertex_groups.new(name='CoveredTop')
coverage.add([v.index for v in obj.data.vertices if v.co.z > 0], 1.0, 'REPLACE')
obj.shape_key_add(name='Basis')
key=obj.shape_key_add(name='Jaw_Wide')
for vertex in key.data: vertex.co.x *= 1.2
mat=bpy.data.materials.new('SkinMat')
mat.use_nodes=True
obj.data.materials.append(mat)
image=bpy.data.images.new('SkinTex', width=2, height=2)
image.pixels[:]=[0.65, 0.54, 0.48, 1.0] * 4
image.pack()
texture=mat.node_tree.nodes.new('ShaderNodeTexImage')
texture.image=image
bsdf=next(node for node in mat.node_tree.nodes if node.type=='BSDF_PRINCIPLED')
mat.node_tree.links.new(texture.outputs['Color'], bsdf.inputs['Base Color'])
for name, x in [('Hair_A', -1.0), ('Hair_B', 1.0)]:
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(x, 0, 0.7))
    bpy.context.object.name=name
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, 0, -1))
bpy.context.object.name='Ground'
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0.5, 0, 0))
bpy.context.object.name='Sword'
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, 0, 2))
bpy.context.object.name='Cover'
for name, x in [('Bra', -0.2), ('Underwear_Bottoms', 0.2)]:
    bpy.ops.mesh.primitive_cube_add(size=0.1, location=(x, 0, -0.5))
    bpy.context.object.name=name
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
""", encoding="utf-8")
            base = root / "base.blend"
            made = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "23",
                                   "--python", str(script), "--", str(base)],
                                  capture_output=True, text=True, check=False)
            self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
            manifest = {"id": "Base_v1", "model": "base.blend",
                        "parameters": {"face.jawWidth": {"shapeKeys": [{"name": "Jaw_Wide"}]}},
                        "modules": {"appearance.hairStyle": {"hair_a": ["Hair_A"], "hair_b": ["Hair_B"]},
                                    "wardrobe.top": {"cover": ["Cover"]}},
                        "bodyMeshMasks": {"wardrobe.top": {"cover": [{"object": "Body", "vertexGroup": "CoveredTop"}]}},
                        "excludeObjects": ["Ground"],
                        "accessories": {"sword": ["Sword"]},
                        "materials": {"skin": ["SkinMat"]}}
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            recipe = {"schema": canonical.SCHEMA, "id": "sample", "name": "Sample",
                      "base": "Base_v1", "seed": 1, "face": {"jawWidth": 0.8},
                      "body": {}, "appearance": {"hairStyle": "hair_a"},
                      "material": {"skinTone": "#DEC6B2"}, "wardrobe": {}}
            out, report = canonical.build(recipe, root / "manifest.json", root / "build",
                                          strict=True, render=False)
            self.assertEqual(report["status"], "ok", (out / "blender.log").read_text(encoding="utf-8"))
            glb = (out / "model.glb").read_bytes()
            length = int.from_bytes(glb[12:16], "little")
            document = json.loads(glb[20:20 + length])
            names = {node.get("name") for node in document["nodes"]}
            self.assertIn("Body", names)
            self.assertIn("Hair_A", names)
            self.assertNotIn("Hair_B", names)
            self.assertNotIn("Ground", names)
            self.assertNotIn("Sword", names)
            self.assertIn("Bra", names)
            self.assertIn("Underwear_Bottoms", names)
            self.assertTrue(any(mesh["primitives"][0].get("targets") for mesh in document["meshes"]))
            self.assertTrue(any(abs(mesh.get("weights", [0])[0] - 0.6) < 0.01
                                for mesh in document["meshes"] if mesh.get("weights")))
            self.assertIn("baseColorTexture", document["materials"][0]["pbrMetallicRoughness"])
            importer = root / "import.py"
            importer.write_text("""
import bpy
import sys
bpy.ops.import_scene.gltf(filepath=sys.argv[-1])
assert any(obj.type == 'MESH' and obj.name == 'Body' for obj in bpy.data.objects)
print('CANONICAL_IMPORT_OK')
""", encoding="utf-8")
            imported = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "23",
                                       "--python", str(importer), "--", str(out / "model.glb")],
                                      capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            self.assertIn("CANONICAL_IMPORT_OK", imported.stdout)

            no_hair = dict(recipe)
            no_hair["id"] = "sample-no-hair"
            no_hair["appearance"] = {}
            no_hair["accessories"] = ["sword"]
            empty_out, empty_report = canonical.build(no_hair, root / "manifest.json",
                                                      root / "build", strict=True, render=False)
            self.assertEqual(empty_report["status"], "ok")
            empty_glb = (empty_out / "model.glb").read_bytes()
            empty_length = int.from_bytes(empty_glb[12:16], "little")
            empty_document = json.loads(empty_glb[20:20 + empty_length])
            empty_names = {node.get("name") for node in empty_document["nodes"]}
            self.assertNotIn("Hair_A", empty_names)
            self.assertNotIn("Hair_B", empty_names)
            self.assertIn("Sword", empty_names)

            covered = dict(recipe, id="sample-covered", wardrobe={"top": "cover"})
            covered_out, covered_report = canonical.build(covered, root / "manifest.json", root / "build",
                                                            strict=True, render=False)
            self.assertEqual(covered_report["status"], "ok")
            data = (covered_out / "model.glb").read_bytes()
            size = int.from_bytes(data[12:16], "little")
            doc = json.loads(data[20:20 + size])
            body_node = next(node for node in doc["nodes"] if node.get("name") == "Body")
            body_mesh = doc["meshes"][body_node["mesh"]]
            primitive = body_mesh["primitives"][0]
            self.assertEqual(doc["accessors"][primitive["indices"]]["count"], 30)
            self.assertTrue(primitive.get("targets"), "Coverage must preserve shape keys")
            self.assertAlmostEqual(body_mesh["weights"][0], .6, places=2)

            undressed = dict(recipe, id="sample-underwear-off",
                             underwear={"top": False, "bottom": False})
            undressed_out, undressed_report = canonical.build(
                undressed, root / "manifest.json", root / "build", strict=True, render=False)
            self.assertEqual(undressed_report["status"], "ok")
            glb = (undressed_out / "model.glb").read_bytes()
            size = int.from_bytes(glb[12:16], "little")
            document = json.loads(glb[20:20 + size])
            names = {node.get("name") for node in document["nodes"]}
            self.assertNotIn("Bra", names)
            self.assertNotIn("Underwear_Bottoms", names)


if __name__ == "__main__":
    unittest.main()
