import math
import unittest
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Bricks, Camera, Color, Curvature, Cylinder, Displace, GenerationInput, Light,
    Material, ModelingError, Noise, Part, QualityProfile, RenderSettings, SimpleDeform, Transform, build_recipe,
    dump_recipe, imperfections, recipe_hash, srgb,
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

    def test_part_texture_resolution(self):
        simple_asset(texture_resolution=2048).validate()
        with self.assertRaises(ModelingError) as ctx:
            simple_asset(texture_resolution=3000).validate()
        self.assertEqual(ctx.exception.code, "part.textureResolution")

    def test_cylinder_segments(self):
        with self.assertRaises(ModelingError):
            Cylinder(segments=2).validate("c")
        Cylinder(segments=None).validate("c")

    def test_render_settings(self):
        with self.assertRaises(ModelingError):
            RenderSettings(views=("oblique",)).validate()
        with self.assertRaises(ModelingError):
            RenderSettings(passes=("xray",)).validate()
        with self.assertRaises(ModelingError):
            RenderSettings(environment="night").validate()
        with self.assertRaises(ModelingError):
            RenderSettings(aspect_ratio=0.2).validate()
        RenderSettings(passes=("shaded", "clay"), environment="sunny").validate()
        self.assertEqual(RenderSettings(aspect_ratio=1.6).to_recipe()["aspect_ratio"], 1.6)
        RenderSettings(environment="C:/somewhere/sky.hdr").validate()

    def test_cameras_and_lights(self):
        cam = Camera("interior", position=(0, 1.5, 3), target=(0, 1, -3), fov=1.2)
        section = Camera("section", position=(1.4, 1.2, 0), target=(0, 1.2, 0), orthographic=True, ortho_scale=9, clip_start=0.001,
                         hide_parts=("ceiling",))
        light = Light("living", position=(0, 2.3, 1.5), energy=60, size=1.0)
        settings = RenderSettings(views=(), cameras=(cam, section), lights=(light,))
        settings.validate()
        recipe = settings.to_recipe()
        self.assertEqual([c["id"] for c in recipe["cameras"]], ["interior", "section"])
        self.assertEqual(recipe["cameras"][1]["hide_parts"], ["ceiling"])
        self.assertEqual(recipe["lights"][0]["energy"], 60.0)
        with self.assertRaises(ModelingError):
            RenderSettings(views=(), cameras=()).validate()
        with self.assertRaises(ModelingError):
            Camera("front", position=(0, 0, 1), target=(0, 0, 0)).validate("c")
        with self.assertRaises(ModelingError):
            Camera("c", position=(0, 0, 0), target=(0, 0, 0)).validate("c")
        with self.assertRaises(ModelingError):
            RenderSettings(cameras=(cam, cam)).validate()
        with self.assertRaises(ModelingError):
            Light("l", position=(0, 0, 0), energy=0).validate("l")
        Bricks(width=0.09, height=0.9, mortar=0.002, axis="y").validate("b")
        with self.assertRaises(ModelingError):
            Bricks(width=0.01, height=0.01, mortar=0.02).validate("b")
        Displace(height=Bricks() * 0.001).validate("d")

    def test_displace_rejects_probe_fields(self):
        Displace(height=imperfections.dents() + imperfections.wobble()).validate("d")
        with self.assertRaises(ModelingError) as ctx:
            Displace(height=Curvature() * 0.001).validate("d")
        self.assertEqual(ctx.exception.code, "displace.field")
        with self.assertRaises(ModelingError):
            Displace(height=None).validate("d")
        recipe = Displace(height=Noise() * 0.001).to_recipe()
        self.assertEqual(recipe["kind"], "displace")
        self.assertEqual(recipe["height"]["kind"], "math")

    def test_simple_deform(self):
        SimpleDeform(method="bend", angle=0.3, axis="y").validate("s")
        with self.assertRaises(ModelingError):
            SimpleDeform(method="fold").validate("s")
        with self.assertRaises(ModelingError):
            SimpleDeform(method="taper", factor=20.0).validate("s")


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


class AssetExtrasTests(unittest.TestCase):
    def test_extras_are_validated_and_in_recipe(self):
        from promodeler.core import Asset, Box, Material, ModelingError, Part, build_recipe
        part = Part("p", Box(size=(0.1, 0.1, 0.1)), "m")
        asset = Asset("x", (Material("m"),), (part,), extras={"physics": {"gravity": [0, -9.81, 0]}, "note": "a"})
        asset.validate()
        self.assertEqual(build_recipe(asset)["asset"]["extras"]["physics"]["gravity"][1], -9.81)
        with self.assertRaises(ModelingError):
            Asset("x", (Material("m"),), (part,), extras={"bad": object()}).validate()
        with self.assertRaises(ModelingError):
            Asset("x", (Material("m"),), (part,), extras=["not", "a", "dict"]).validate()
