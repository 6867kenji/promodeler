import math
import unittest
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Color, Cylinder, GenerationInput, Material, ModelingError, Part,
    QualityProfile, RenderSettings, Transform, build_recipe, dump_recipe, recipe_hash, srgb,
)


def simple_asset(**overrides) -> Asset:
    material = Material("m", base_color=srgb(0.5, 0.5, 0.5))
    part = Part(id="a", shape=Box(), material="m", **overrides)
    return Asset(name="Simple", materials=(material,), parts=(part,))


class ValidationTests(unittest.TestCase):
    def test_valid_asset(self):
        simple_asset().validate()

    def test_unknown_material(self):
        asset = Asset(name="x", materials=(), parts=(Part(id="a", shape=Box(), material="none"),))
        with self.assertRaises(ModelingError) as ctx:
            asset.validate()
        self.assertEqual(ctx.exception.code, "part.material")

    def test_duplicate_part(self):
        m = Material("m")
        asset = Asset(name="x", materials=(m,), parts=(Part("a", Box(), "m"), Part("a", Box(), "m")))
        with self.assertRaises(ModelingError) as ctx:
            asset.validate()
        self.assertEqual(ctx.exception.code, "part.duplicateID")

    def test_parent_cycle(self):
        m = Material("m")
        asset = Asset(name="x", materials=(m,), parts=(
            Part("a", Box(), "m", parent="b"), Part("b", Box(), "m", parent="a")))
        with self.assertRaises(ModelingError) as ctx:
            asset.validate()
        self.assertEqual(ctx.exception.code, "part.parentCycle")

    def test_opaque_alpha_rejected(self):
        with self.assertRaises(ModelingError) as ctx:
            Material("m", base_color=Color(1, 1, 1, 0.5)).validate()
        self.assertEqual(ctx.exception.code, "material.alphaMode")

    def test_negative_size(self):
        with self.assertRaises(ModelingError) as ctx:
            simple_asset().parts[0].__class__(id="a", shape=Box(size=(1, -1, 1)), material="m").validate()
        self.assertEqual(ctx.exception.code, "box.size")

    def test_nonfinite_transform(self):
        with self.assertRaises(ModelingError):
            Transform(translation=(0.0, float("nan"), 0.0)).validate("t")

    def test_bevel_domain(self):
        with self.assertRaises(ModelingError):
            Bevel(width=0.0).validate("b")
        with self.assertRaises(ModelingError):
            Bevel(segments=0).validate("b")
        Bevel(width=0.01, segments=4, angle_limit=math.radians(30)).validate("b")

    def test_cylinder_segments(self):
        with self.assertRaises(ModelingError):
            Cylinder(segments=2).validate("c")
        Cylinder(segments=None).validate("c")

    def test_render_settings(self):
        with self.assertRaises(ModelingError):
            RenderSettings(views=("oblique",)).validate()
        RenderSettings().validate()


class RecipeTests(unittest.TestCase):
    def test_recipe_is_canonical_and_stable(self):
        asset = simple_asset()
        a = dump_recipe(build_recipe(asset))
        b = dump_recipe(build_recipe(simple_asset()))
        self.assertEqual(a, b)
        self.assertNotIn(" ", a)
        self.assertIn('"recipe_version":1', a)

    def test_hash_changes_with_environment_and_content(self):
        recipe = build_recipe(simple_asset())
        h1 = recipe_hash(recipe, kernel_version=1, blender="5.1.2")
        h2 = recipe_hash(recipe, kernel_version=2, blender="5.1.2")
        h3 = recipe_hash(build_recipe(simple_asset(transform=Transform(translation=(1, 0, 0)))), kernel_version=1, blender="5.1.2")
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 64)

    def test_color_roundtrip(self):
        c = srgb(0.5, 0.2, 0.9)
        lin = c.to_linear()
        back = Color.from_linear(*lin)
        for x, y in zip(c.to_recipe(), back.to_recipe()):
            self.assertAlmostEqual(x, y, places=6)


class GeneratorTests(unittest.TestCase):
    def test_generate_validates_parameters_and_result(self):
        @dataclass(frozen=True)
        class P:
            size: float = 1.0

        def validate(p: P):
            if p.size <= 0:
                raise ModelingError("p.size", "size must be positive")

        def build(input: GenerationInput) -> Asset:
            m = Material("m")
            return Asset("G", (m,), (Part("a", Box(size=(input.parameters.size,) * 3), "m"),))

        gen = AssetGenerator(name="G", parameters=P(), build=build, validate=validate, seed=3)
        asset = gen.generate()
        self.assertEqual(asset.parts[0].shape.size, (1.0, 1.0, 1.0))
        with self.assertRaises(ModelingError):
            gen.generate(gen.make_input(parameters=P(size=-1)))
        recipe = build_recipe(asset, gen.make_input(), parameters=gen.parameters_recipe(P()), generator_version=gen.version)
        self.assertEqual(recipe["input"]["parameters"], {"size": 1.0})
        self.assertEqual(recipe["input"]["seed"], 3)
        self.assertEqual(recipe["input"]["quality"], QualityProfile().to_recipe())


if __name__ == "__main__":
    unittest.main()
