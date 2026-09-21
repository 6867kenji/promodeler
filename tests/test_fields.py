import unittest

from promodeler.core import (
    Cavity, Curvature, Layer, Material, ModelingError, Noise, Voronoi, presets, srgb,
)
from promodeler.core.fields import Const, Math, MAX_DEPTH


class FieldTests(unittest.TestCase):
    def test_operators_build_math_nodes(self):
        f = 0.5 + Noise(size=0.01) * 0.2 - Curvature() / 2
        self.assertIsInstance(f, Math)
        recipe = f.to_recipe()
        self.assertEqual(recipe["kind"], "math")
        self.assertEqual(recipe["operation"], "subtract")
        self.assertEqual(recipe["a"]["a"], {"kind": "const", "value": 0.5})
        f.validate("f")

    def test_smoothstep_clamp_ramp_serialize(self):
        f = Noise().smoothstep(0.3, 0.6).clamp() .ramp([(0, 0), (1, 0.5)])
        r = f.to_recipe()
        self.assertEqual(r["kind"], "ramp")
        self.assertEqual(r["stops"], [[0.0, 0.0], [1.0, 0.5]])
        self.assertEqual(r["field"]["kind"], "clamp")
        f.validate("f")

    def test_invalid_parameters(self):
        with self.assertRaises(ModelingError):
            Noise(size=0.0).validate("n")
        with self.assertRaises(ModelingError):
            Voronoi(feature="f9").validate("v")
        with self.assertRaises(ModelingError):
            Cavity(distance=-1).validate("c")
        with self.assertRaises(ModelingError):
            Noise().smoothstep(0.7, 0.2).validate("s")

    def test_depth_limit(self):
        f = Const(0.0)
        for _ in range(MAX_DEPTH + 2):
            f = f + 1.0
        with self.assertRaises(ModelingError) as ctx:
            f.validate("deep")
        self.assertEqual(ctx.exception.code, "field.depth")

    def test_anisotropic_size(self):
        Noise(size=(0.1, 0.01, 0.1)).validate("n")
        with self.assertRaises(ModelingError):
            Noise(size=(0.1, 0.01)).validate("n")


class MaterialTests(unittest.TestCase):
    def test_constant_material_does_not_bake(self):
        m = Material("m", base_color=srgb(0.5, 0.5, 0.5), roughness=0.3)
        m.validate()
        self.assertFalse(m.needs_bake)
        r = m.to_recipe()
        self.assertFalse(r["needs_bake"])
        self.assertEqual(r["roughness"], {"kind": "const", "value": 0.3})
        self.assertEqual(r["base_color"]["kind"], "color")

    def test_field_channel_needs_bake(self):
        m = Material("m", roughness=Noise())
        self.assertTrue(m.needs_bake)
        m.validate()

    def test_layer_requires_a_channel(self):
        with self.assertRaises(ModelingError) as ctx:
            Material("m", layers=(Layer(mask=0.5),)).validate()
        self.assertEqual(ctx.exception.code, "layer.empty")

    def test_layer_channel_types(self):
        with self.assertRaises(ModelingError):
            Material("m", layers=(Layer(roughness=srgb(1, 1, 1)),)).validate()
        with self.assertRaises(ModelingError):
            Material("m", layers=(Layer(base_color=0.5),)).validate()

    def test_presets_validate_and_serialize(self):
        for factory in (presets.worn_leather, presets.rusty_iron, presets.painted_metal):
            m = factory(seed=2)
            m.validate()
            self.assertTrue(m.needs_bake)
            recipe = m.to_recipe()
            self.assertTrue(recipe["layers"])
            self.assertEqual(factory(seed=2).to_recipe(), recipe)
            self.assertNotEqual(factory(seed=3).to_recipe(), recipe)


if __name__ == "__main__":
    unittest.main()
