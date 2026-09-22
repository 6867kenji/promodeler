import glob
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from promodeler.character import Catalog, CharacterRecipe, OutfitRecipe, canonical_dump, recipe_hash
from promodeler.character import check, consistency, schema, serialize
from promodeler.character.cli import json_diff
from promodeler.character.from_blueprint import character_from_blueprint, load_blueprint, outfit_from_blueprint
from promodeler.character.recipe import SCHEMA, Body, CrossSection, Garment, Measurements, RecipeWarning
from promodeler.core import ModelingError

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINTS = sorted(glob.glob(str(ROOT / "blueprints" / "japan-realistic-v1" / "*" / "blueprint.json")))


def character_blueprints():
    for path in BLUEPRINTS:
        blueprint = load_blueprint(path)
        if blueprint.get("kind") in ("humanoid", "wearable"):
            yield blueprint


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def test_loads_every_category_with_unique_ids(self):
        self.assertGreater(len(self.catalog.entries), 50)
        self.assertEqual(len(self.catalog.version), 12)
        self.assertIn("wardrobe", self.catalog.files)
        for entry in self.catalog.entries.values():
            if entry.category in ("wardrobe", "footwear"):
                self.assertTrue(entry.slots, entry.id)

    def test_match_prefers_priority_then_longest_fragment(self):
        self.assertEqual(self.catalog.match_text("短い黒髪、左分け、面長", "hair").id, "hair_short_side_part_01")
        self.assertEqual(self.catalog.match_text("黒テーパードパンツ", "wardrobe", slot="lower").id, "pants_tapered_01")
        self.assertIsNone(self.catalog.match_text("該当なし", "wardrobe"))

    def test_nearest_color(self):
        self.assertEqual(self.catalog.nearest_color("skin", "#DFC1AD").id, "skin_jp_light_02")

    def test_license_policy(self):
        entry = self.catalog.get("slacks_01")
        forbidden = replace(entry, license=replace(entry.license, type="CC-BY-NC-4.0"))
        with self.assertRaises(ModelingError) as ctx:
            self.catalog.check(forbidden)
        self.assertEqual(ctx.exception.code, "catalog.license")
        attribution = replace(entry, license=replace(entry.license, type="CC-BY-4.0", attribution=None))
        with self.assertRaises(ModelingError):
            self.catalog.check(attribution)
        codes = {w.code for w in self.catalog.check(entry, slot="lower", race="human_male")}
        self.assertEqual(codes, {"catalog.placeholder"})
        with self.assertRaises(ModelingError) as ctx:
            self.catalog.check(entry, slot="upper")
        self.assertEqual(ctx.exception.code, "catalog.slot")

    def test_unknown_id(self):
        with self.assertRaises(ModelingError) as ctx:
            self.catalog.get("nope")
        self.assertEqual(ctx.exception.code, "catalog.unknown")


class BlueprintConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.characters = {}
        cls.outfits = {}
        for blueprint in character_blueprints():
            if blueprint["kind"] == "humanoid":
                recipe, warnings = character_from_blueprint(blueprint, cls.catalog)
                cls.characters[recipe.id] = (recipe, warnings)
            else:
                outfit, warnings = outfit_from_blueprint(blueprint, cls.catalog)
                cls.outfits[outfit.id] = (outfit, warnings)

    def test_all_seventeen_convert_and_validate(self):
        self.assertEqual(len(self.characters), 15)
        self.assertEqual(len(self.outfits), 2)
        for recipe, warnings in self.characters.values():
            warnings = list(warnings) + recipe.validate(self.catalog)
            hard = [w for w in warnings if w.code not in ("catalog.placeholder", "accessory.missingAsset")]
            self.assertEqual(hard, [], recipe.id)
        for outfit, warnings in self.outfits.values():
            base = self.characters[outfit.base_character][0]
            warnings = list(warnings) + outfit.validate(self.catalog, base=base)
            self.assertEqual([w for w in warnings if w.code != "catalog.placeholder"], [], outfit.id)

    def test_every_wardrobe_slot_resolves(self):
        for recipe, _ in self.characters.values():
            for garment in recipe.wardrobe:
                self.assertIsNotNone(garment.catalog_id, f"{recipe.id} {garment.slot} {garment.name}")
            self.assertIsNotNone(recipe.appearance.hair.style, recipe.id)

    def test_businessman_mapping(self):
        recipe, _ = self.characters["businessman"]
        self.assertEqual(recipe.seed, 22)
        self.assertEqual(recipe.identity.sex, "male")
        self.assertEqual(recipe.base.race, "human_male")
        self.assertEqual(recipe.body.measurements_m.barefoot_height, 1.76)
        self.assertEqual(recipe.body.measurements_m.circumferences, {"chest": 0.96, "waist": 0.83, "hip": 0.95})
        self.assertEqual([s.landmark for s in recipe.body.measurements_m.cross_sections], ["chest", "waist", "hip"])
        self.assertEqual(recipe.body.tolerances_m["barefoot_height"], 0.002)
        self.assertEqual(recipe.face.shape["face_length"], 0.7)
        self.assertEqual(recipe.face.metrics_m["iris_diameter"], 0.0115)
        self.assertEqual(recipe.appearance.hair.style, "hair_short_side_part_01")
        self.assertEqual(recipe.appearance.hair.base_color_srgb, "#28201D")
        self.assertEqual(recipe.appearance.facial_hair.style, "stubble_light_01")
        slots = {g.slot: g.catalog_id for g in recipe.wardrobe}
        self.assertEqual(slots, {"upper": "suit_jacket_2button_01", "lower": "slacks_01", "inner": "dress_shirt_01",
                                 "neck": "necktie_01", "footwear": "oxford_lace_01"})
        footwear = next(g for g in recipe.wardrobe if g.slot == "footwear")
        self.assertEqual((footwear.sole_height_m, footwear.internal_length_m), (0.025, 0.277))
        self.assertEqual([(a.id, a.socket, a.source.path) for a in recipe.accessories], [("briefcase", "hand_r", "assets/props/briefcase.py")])
        self.assertEqual(recipe.target["engine"], "unity_hdrp")
        self.assertEqual([c.id for c in recipe.animation.clips][:2], ["idle", "walk"])
        self.assertIn("vowel_o", recipe.animation.face_shapes)
        self.assertEqual(recipe.source.kind, "blueprint")
        self.assertTrue(recipe.source.path.startswith("blueprints/japan-realistic-v1/22-businessman"))

    def test_woman_uses_parts_and_summary(self):
        recipe, _ = self.characters["woman"]
        self.assertEqual(recipe.identity.sex, "female")
        self.assertEqual(recipe.body.measurements_m.head_height, 0.218)
        self.assertEqual(len(recipe.body.measurements_m.cross_sections), 7)
        self.assertEqual({g.slot: g.catalog_id for g in recipe.wardrobe}, {"dress": "dress_sleeveless_uneck_01", "footwear": "sneaker_low_01"})
        self.assertEqual(recipe.face.metrics_m["mouth_width"], 0.044)
        self.assertEqual(recipe.appearance.hair.length_m, 0.66)
        self.assertEqual(recipe.appearance.eyes.iris_color_srgb, "#574335")

    def test_karate_master_is_barefoot(self):
        recipe, _ = self.characters["karate-master"]
        self.assertFalse(any(g.slot == "footwear" for g in recipe.wardrobe))
        self.assertGreater(recipe.body.shape["muscle"], 0.6)

    def test_outfits(self):
        karate, _ = self.outfits["haruka-karate-uniform"]
        self.assertEqual(karate.base_character, "woman")
        self.assertTrue(karate.barefoot)
        self.assertEqual(karate.hair_override.style, "hair_long_braided_back_01")
        self.assertEqual([c.id for c in karate.clips_extra], ["karate"])
        self.assertEqual(karate.extra_bones, ("belt-end.L", "belt-end.R"))
        self.assertEqual(karate.controls["waist_wraps"], 2)
        riding, _ = self.outfits["haruka-riding-suit"]
        self.assertFalse(riding.barefoot)
        self.assertEqual({g.slot for g in riding.wardrobe}, {"upper", "lower", "inner", "hands", "footwear"})
        boots = next(g for g in riding.wardrobe if g.slot == "footwear")
        self.assertEqual(boots.sole_height_m, 0.035)

    def test_conversion_is_deterministic(self):
        blueprint = load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "22-businessman" / "blueprint.json")
        a, _ = character_from_blueprint(blueprint, self.catalog)
        b, _ = character_from_blueprint(blueprint, self.catalog)
        self.assertEqual(a.canonical(), b.canonical())
        self.assertEqual(a.hash(), b.hash())
        self.assertNotEqual(a.hash(), replace(a, seed=99).hash())
        self.assertNotEqual(a.hash(), a.hash(catalog_version="other"))

    def test_json_round_trip(self):
        for recipe, _ in self.characters.values():
            data = json.loads(json.dumps(recipe.to_json(), ensure_ascii=False))
            self.assertEqual(CharacterRecipe.from_json(data), recipe)
        for outfit, _ in self.outfits.values():
            self.assertEqual(OutfitRecipe.from_json(json.loads(json.dumps(outfit.to_json()))), outfit)

    def test_non_character_blueprint_rejected(self):
        blueprint = load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "07-bed" / "blueprint.json")
        with self.assertRaises(ModelingError) as ctx:
            character_from_blueprint(blueprint, self.catalog)
        self.assertEqual(ctx.exception.code, "character.kind")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        blueprint = load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "22-businessman" / "blueprint.json")
        self.recipe, _ = character_from_blueprint(blueprint, self.catalog)

    def test_unknown_field_and_missing_field(self):
        data = self.recipe.to_json()
        data["extra"] = 1
        with self.assertRaises(ModelingError) as ctx:
            CharacterRecipe.from_json(data)
        self.assertEqual(ctx.exception.code, "recipe.unknownField")
        data = self.recipe.to_json()
        del data["id"]
        with self.assertRaises(ModelingError) as ctx:
            CharacterRecipe.from_json(data)
        self.assertEqual(ctx.exception.code, "recipe.missingField")

    def test_enum_and_pattern_enforced(self):
        bad = replace(self.recipe, wardrobe=(Garment(slot="cape"),))
        with self.assertRaises(ModelingError) as ctx:
            bad.validate()
        self.assertEqual(ctx.exception.code, "recipe.enum")
        bad = replace(self.recipe, id="Bad Id")
        with self.assertRaises(ModelingError) as ctx:
            bad.validate()
        self.assertEqual(ctx.exception.code, "recipe.pattern")

    def test_duplicate_slot_and_unknown_catalog_id(self):
        garment = self.recipe.wardrobe[0]
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, wardrobe=(garment, garment)).validate()
        self.assertEqual(ctx.exception.code, "wardrobe.slot")
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, wardrobe=(replace(garment, catalog_id="ghost"),)).validate(self.catalog)
        self.assertEqual(ctx.exception.code, "catalog.unknown")
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, wardrobe=(replace(garment, catalog_id="slacks_01"),)).validate(self.catalog)  # upper slot, lower garment
        self.assertEqual(ctx.exception.code, "catalog.slot")

    def test_body_domain(self):
        body = self.recipe.body
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, body=replace(body, shape={"muscle": 1.5})).validate()
        self.assertEqual(ctx.exception.code, "body.shape")
        bad = replace(body, measurements_m=replace(body.measurements_m, circumferences={"neck": 0.4}))
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, body=bad).validate()
        self.assertEqual(ctx.exception.code, "measurements.key")
        with self.assertRaises(ModelingError) as ctx:
            replace(self.recipe, body=Body(Measurements(barefoot_height=0.5))).validate()
        self.assertEqual(ctx.exception.code, "recipe.range")

    def test_unresolved_slot_is_a_warning(self):
        garment = replace(self.recipe.wardrobe[0], catalog_id=None)
        warnings = replace(self.recipe, wardrobe=(garment,)).validate(self.catalog)
        self.assertIn("wardrobe.unresolved", {w.code for w in warnings})


class ConsistencyTests(unittest.TestCase):
    def test_ellipse_perimeter(self):
        self.assertAlmostEqual(consistency.ellipse_perimeter(0.2, 0.2), 0.2 * 3.14159265, places=5)
        self.assertAlmostEqual(consistency.ellipse_perimeter(0.285, 0.205), 0.775, places=3)

    def test_woman_hip_contradiction_is_detected(self):
        catalog = Catalog()
        recipe, _ = character_from_blueprint(load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "05-woman" / "blueprint.json"), catalog)
        warnings = consistency.static_checks(recipe.body.measurements_m)
        hip = [w for w in warnings if w.code == "measurements.sectionVsCircumference" and w.message.startswith("hip")]
        self.assertEqual(len(hip), 1)
        self.assertIn("-95 mm", hip[0].message)

    def test_consistent_sections_pass(self):
        m = Measurements(barefoot_height=1.76, inseam=0.8, shoulder_width=0.44, foot_length=0.265, circumferences={"chest": 0.96},
                         cross_sections=(CrossSection("chest", 1.375, 0.3264, 0.284),))
        self.assertEqual(consistency.static_checks(m), [])

    def test_mhr_landmarks_from_sections(self):
        m = Measurements(barefoot_height=1.76, cross_sections=(CrossSection("chest", 1.375), CrossSection("waist", 1.166), CrossSection("hip", 1.045)))
        landmarks = consistency.mhr_landmarks(m)
        self.assertEqual(landmarks["shoulders"], consistency.ACROMION_FRACTION)
        self.assertAlmostEqual(landmarks["bust"], 1.375 / 1.76, places=5)
        self.assertNotIn("chest", landmarks)
        self.assertEqual(set(landmarks), {"shoulders", "bust", "waist", "hip"})

    def test_mhr_targets_vocabulary(self):
        m = Measurements(barefoot_height=1.76, circumferences={"chest": 0.96, "hip": 0.95}, cross_sections=(CrossSection("chest", 1.375, 0.33, 0.28),))
        targets = consistency.mhr_targets(m)
        self.assertEqual(targets, {"height": 1.76, "bust": 0.96, "hip": 0.95, "bust_width": 0.33, "bust_depth": 0.28})


class CheckTests(unittest.TestCase):
    def test_rows_against_build(self):
        catalog = Catalog()
        recipe, _ = character_from_blueprint(load_blueprint(ROOT / "blueprints" / "japan-realistic-v1" / "22-businessman" / "blueprint.json"), catalog)
        build = {"status": "ok", "measured_m": {"barefoot_height": 1.7615, "chest": 0.972}, "totals": {"triangles": 96300},
                 "warnings": [{"code": "resolve.residual", "message": "x"}], "seconds": 1}
        rows, budgets, warnings = check.compare(recipe, build)
        by_label = {r.label: r for r in rows}
        self.assertEqual(by_label["barefoot_height"].status, "ok")
        self.assertEqual(by_label["chest circumference"].status, "OVER")
        self.assertEqual(budgets[0].got, 96300)
        self.assertIn("resolve.residual", {w.code for w in warnings})
        text = check.format_table(recipe, rows, budgets, warnings, "test")
        self.assertIn("OVER", text)


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


class SchemaTests(unittest.TestCase):
    def test_committed_schemas_match_dataclasses(self):
        self.assertEqual(schema.check_all(), [], "run `python -m promodeler character schema --write`")

    def test_schema_shape(self):
        generated = schema.generate("character_recipe")
        self.assertEqual(generated["title"], "CharacterRecipe")
        self.assertEqual(generated["properties"]["schema"]["enum"], [SCHEMA])
        garment = generated["$defs"]["Garment"]
        self.assertIn("inner", garment["properties"]["slot"]["enum"])
        self.assertEqual(garment["properties"]["deformation"]["type"], ["string", "null"])
        self.assertIn(None, garment["properties"]["deformation"]["enum"])

    @unittest.skipUnless(_has_jsonschema(), "jsonschema not installed")
    def test_recipes_validate_against_schema(self):
        catalog = Catalog()
        for blueprint in character_blueprints():
            if blueprint["kind"] == "humanoid":
                recipe, _ = character_from_blueprint(blueprint, catalog)
                self.assertEqual(schema.validate_with_jsonschema(recipe.to_json(), "character_recipe"), [], recipe.id)


class SerializeTests(unittest.TestCase):
    def test_diff_and_canonical(self):
        old = {"a": 1, "b": {"c": [1, 2]}, "d": "x"}
        new = {"a": 1, "b": {"c": [1, 3]}, "e": True}
        lines = json_diff(old, new)
        self.assertEqual(len(lines), 3)
        self.assertTrue(any(line.startswith("$.b.c[1]") for line in lines))
        self.assertEqual(canonical_dump({"b": 1, "a": 2}), '{"a":2,"b":1}')
        self.assertEqual(len(recipe_hash({"a": 1})), 64)

    def test_decode_type_errors(self):
        with self.assertRaises(ModelingError) as ctx:
            serialize.decode(RecipeWarning, {"code": 1, "message": "m"})
        self.assertEqual(ctx.exception.code, "recipe.type")


class RecipeFilesTests(unittest.TestCase):
    """The committed recipes stay loadable and equal to their regenerated form (until someone edits them on purpose)."""

    def test_committed_recipes_load(self):
        paths = sorted(glob.glob(str(ROOT / "character" / "recipes" / "*.json"))) + sorted(glob.glob(str(ROOT / "character" / "outfits" / "*.json")))
        self.assertGreaterEqual(len(paths), 17)
        catalog = Catalog()
        for path in paths:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            recipe = CharacterRecipe.from_json(data) if data["schema"] == SCHEMA else OutfitRecipe.from_json(data)
            recipe.validate(catalog)


if __name__ == "__main__":
    unittest.main()
