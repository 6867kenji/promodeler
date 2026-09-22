import unittest


from promodeler.core import ModelingError, Profile, Strands, Sweep, curves
from promodeler.core import meshgen


def tube(x: float) -> Sweep:
    return Sweep(profile=Profile(curves.circle(0.002, 8)), path=((x, 0.0, 0.0), (x, 0.1, 0.0), (x, 0.2, 0.02)))


class StrandsTests(unittest.TestCase):
    def test_merged_mesh_counts(self):
        shape = Strands(strands=(tube(0.0), tube(0.05)))
        shape.validate("s")
        spec = meshgen.generate(shape.to_recipe(), {"curve_segments": 8, "surface_segments": 8})
        single = meshgen.generate(tube(0.0).to_recipe(), {"curve_segments": 8, "surface_segments": 8})
        self.assertEqual(len(spec.vertices), 2 * len(single.vertices))
        self.assertEqual(len(spec.faces), 2 * len(single.faces))
        self.assertEqual(max(max(f) for f in spec.faces), len(spec.vertices) - 1)

    def test_validation(self):
        with self.assertRaises(ModelingError) as ctx:
            Strands(strands=()).validate("s")
        self.assertEqual(ctx.exception.code, "strands.count")
        with self.assertRaises(ModelingError) as ctx:
            Strands(strands=("no",)).validate("s")
        self.assertEqual(ctx.exception.code, "strands.kind")
        bad = Sweep(profile=Profile(curves.circle(0.002, 8)), path=((0, 0, 0), (0, 0, 0)))
        with self.assertRaises(ModelingError):
            Strands(strands=(bad,)).validate("s")


if __name__ == "__main__":
    unittest.main()


class SweepUpTests(unittest.TestCase):
    def test_up_orients_the_first_profile_axis(self):
        # Path along +Y: the default reference (+Y) is degenerate and falls back to +X; an explicit up of +Z
        # must put the profile's u axis along +Z instead.
        base = dict(profile=Profile(((0.01, 0.0), (0.0, 0.004), (-0.01, 0.0), (0.0, -0.004))),
                    path=((0.0, 0.0, 0.0), (0.0, 0.1, 0.0)))
        default = meshgen.generate(Sweep(**base).to_recipe(), {})
        oriented = meshgen.generate(Sweep(**base, up=(0.0, 0.0, 1.0)).to_recipe(), {})
        self.assertAlmostEqual(abs(default.vertices[0][0]), 0.01, places=6)
        self.assertAlmostEqual(abs(oriented.vertices[0][2]), 0.01, places=6)
        with self.assertRaises(ModelingError):
            Sweep(**base, up=(0.0, 0.0, 0.0)).validate("s")
