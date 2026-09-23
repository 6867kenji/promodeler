"""`promodeler character prompt`: rule-based spec extraction, deterministic recipes, and the schema-constrained LLM seam."""

import unittest
from types import SimpleNamespace

from promodeler.character import prompt, sampler
from promodeler.character.catalog import Catalog
from promodeler.core import ModelingError


class PromptParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.presets = sampler.load_presets()

    def test_salaryman_sentence(self):
        spec = prompt.parse_prompt("30代の男性会社員。身長178cm、がっしりした体型。黒縁眼鏡にブリーフケース。", self.catalog)
        self.assertEqual((spec.sex, spec.age, spec.height_m, spec.style), ("male", 35, 1.78, "business"))
        self.assertEqual(spec.body_fat, 0.6)
        self.assertEqual(spec.accessories, ("glasses", "briefcase"))
        self.assertIn("がっしり", spec.descriptors)

    def test_cafe_clerk_sentence_keeps_the_most_specific_garment_per_slot(self):
        spec = prompt.parse_prompt("20代女性。小柄で細身、丸顔。黒髪のボブ。カフェ店員で七分袖シャツにエプロン。", self.catalog)
        self.assertEqual((spec.sex, spec.age, spec.style, spec.hair_style, spec.hair_color_srgb), ("female", 25, "uniform", "hair_bob_01", "#1E1A18"))
        self.assertEqual(spec.height_m, 1.52)   # 小柄 = base height - 6 cm
        self.assertEqual(set(spec.garments), {"shirt_three_quarter_01", "apron_bib_01"})
        self.assertEqual(spec.face_shape["face_length"], 0.38)

    def test_beard_and_hair_color(self):
        spec = prompt.parse_prompt("50代の痩せた男性。白髪、無精ひげ。休日の私服でリュック。", self.catalog)
        self.assertEqual((spec.sex, spec.age, spec.style, spec.facial_hair, spec.hair_color_srgb), ("male", 55, "casual", True, "#8A8683"))
        self.assertEqual(spec.accessories, ("backpack",))
        clean = prompt.parse_prompt("ひげなしの男性", self.catalog)
        self.assertFalse(clean.facial_hair)

    def test_recipe_is_deterministic_and_honours_the_spec(self):
        text = "20代女性。小柄で細身、丸顔。黒髪のボブ。カフェ店員で七分袖シャツにエプロン。"
        a, warnings = prompt.character_from_prompt(text, self.catalog, presets=self.presets)
        b, _ = prompt.character_from_prompt(text, self.catalog, presets=self.presets)
        self.assertEqual(a.canonical(), b.canonical())
        self.assertEqual(a.source.kind, "prompt")
        self.assertEqual(a.identity.sex, "female")
        self.assertEqual(a.identity.age, 25)
        self.assertEqual(a.body.measurements_m.barefoot_height, 1.52)
        self.assertEqual(a.body.shape["body_fat"], 0.3)
        self.assertEqual(a.appearance.hair.style, "hair_bob_01")
        self.assertEqual(a.appearance.hair.base_color_srgb, "#1E1A18")
        ids = {g.slot: g.catalog_id for g in a.wardrobe}
        self.assertEqual(ids["inner"], "shirt_three_quarter_01")
        self.assertEqual(ids["waist"], "apron_bib_01")
        self.assertEqual(a.face.shape["face_length"], 0.38)
        self.assertTrue(a.identity.descriptors[1].startswith("prompt:"))
        self.assertFalse(any(w.code.startswith("measurements.") for w in warnings + a.validate(self.catalog)))
        self.assertTrue(a.id.startswith("prompt-"))

    def test_unknown_garment_and_accessory_warn_instead_of_failing(self):
        spec = prompt.PromptSpec(sex="male", garments=("tuxedo_99",), accessories=("umbrella",))
        recipe, warnings = prompt.character_from_prompt("x", self.catalog, spec=spec, presets=self.presets)
        codes = {w.code for w in warnings}
        self.assertIn("wardrobe.unknown", codes)
        self.assertIn("accessory.unknown", codes)
        self.assertEqual(recipe.identity.sex, "male")

    def test_spec_schema_and_roundtrip(self):
        schema = prompt.spec_schema()
        self.assertEqual(schema["properties"]["style"]["enum"], list(prompt.STYLES) + [None])   # optional field: null is allowed
        spec = prompt.PromptSpec.from_json({"sex": "female", "height_m": 1.6, "garments": ["tshirt_01"]})
        self.assertEqual(spec.height_m, 1.6)
        with self.assertRaises(ModelingError):
            prompt.PromptSpec.from_json({"sex": "robot"})

    def test_llm_path_uses_a_forced_tool_call_and_validates_the_result(self):
        calls = []

        class FakeMessages:
            def create(self, **kwargs):
                calls.append(kwargs)
                block = SimpleNamespace(type="tool_use", name="emit_prompt_spec",
                                        input={"sex": "female", "age": 28, "height_m": 1.62, "style": "business", "garments": ["blouse_01"], "accessories": ["tote"]})
                return SimpleNamespace(content=[block])

        client = SimpleNamespace(messages=FakeMessages())
        spec = prompt.spec_from_llm("28歳の女性、ブラウスにトート", catalog=self.catalog, client=client)
        self.assertEqual(spec.age, 28)
        self.assertEqual(spec.garments, ("blouse_01",))
        self.assertEqual(calls[0]["tool_choice"], {"type": "tool", "name": "emit_prompt_spec"})
        self.assertEqual(calls[0]["tools"][0]["input_schema"]["properties"]["style"]["enum"], list(prompt.STYLES) + [None])
        self.assertIn("hair_bob_01", calls[0]["system"])

        class BadMessages(FakeMessages):
            def create(self, **kwargs):
                return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="emit_prompt_spec", input={"sex": "robot"})])

        with self.assertRaises(ModelingError) as ctx:
            prompt.spec_from_llm("x", catalog=self.catalog, client=SimpleNamespace(messages=BadMessages()))
        self.assertEqual(ctx.exception.code, "prompt.llm")


if __name__ == "__main__":
    unittest.main()
