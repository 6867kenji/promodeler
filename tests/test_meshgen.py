import math
import unittest

from promodeler.core import (
    Extrude, Loft, LoftSection, ModelingError, Profile, Revolve, Sweep, Transform, curves,
)
from promodeler.core.mathutil import euler_xyz, face_normal, polygon_volume, transform_point, trs
from promodeler.core.meshgen import generate

QUALITY = {"curve_segments": 64, "surface_segments": 16}


def volume(spec) -> float:
    """Volume of spec faces; fills (caps with holes) are triangulated by fanning each loop pair."""
    if spec.fills:
        raise AssertionError("volume() expects specs without fills")
    return polygon_volume(spec.vertices, spec.faces)


def bounds(spec):
    xs, ys, zs = zip(*spec.vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def assert_outward(test, spec, center):
    for face in spec.faces:
        n = face_normal(spec.vertices, face)
        c = [sum(spec.vertices[i][k] for i in face) / len(face) for k in range(3)]
        outward = sum(n[k] * (c[k] - center[k]) for k in range(3))
        test.assertGreater(outward, 0.0, f"face {face} points inward")


class MathTests(unittest.TestCase):
    def test_euler_xyz_matches_blender_order(self):
        m = trs((0, 0, 0), (0, 0, math.pi / 2), (1, 1, 1))
        p = transform_point(m, (1, 0, 0))
        self.assertAlmostEqual(p[0], 0.0)
        self.assertAlmostEqual(p[1], 1.0)
        rx = euler_xyz(math.pi / 2, 0, 0)
        # Rotating +Y about X by 90 degrees yields +Z.
        self.assertAlmostEqual(rx[2][1], 1.0)


class ExtrudeTests(unittest.TestCase):
    def test_box_profile_dimensions_and_volume(self):
        shape = Extrude(profile=Profile(curves.rect(2.0, 1.0)), depth=0.5, axis="y")
        shape.validate("s")
        spec = generate(shape.to_recipe(), QUALITY)
        lo, hi = bounds(spec)
        self.assertAlmostEqual(hi[0] - lo[0], 2.0)
        self.assertAlmostEqual(hi[1] - lo[1], 0.5)
        self.assertAlmostEqual(hi[2] - lo[2], 1.0)
        self.assertAlmostEqual(lo[1], 0.0)
        self.assertAlmostEqual(volume(spec), 1.0, places=6)
        assert_outward(self, spec, (0, 0.25, 0))

    def test_clockwise_input_is_normalized(self):
        ring = tuple(reversed(curves.rect(1.0, 1.0)))
        spec = generate(Extrude(profile=Profile(ring), depth=1.0).to_recipe(), QUALITY)
        self.assertAlmostEqual(volume(spec), 1.0, places=6)

    def test_axis_z_faces_viewer(self):
        spec = generate(Extrude(profile=Profile(curves.rect(1.0, 1.0)), depth=2.0, axis="z").to_recipe(), QUALITY)
        lo, hi = bounds(spec)
        self.assertAlmostEqual(hi[2] - lo[2], 2.0)
        self.assertAlmostEqual(volume(spec), 2.0, places=6)

    def test_holes_produce_fills(self):
        profile = Profile(curves.rect(2.0, 2.0), holes=(curves.circle(0.5, 16),))
        profile.validate()
        spec = generate(Extrude(profile=profile, depth=1.0).to_recipe(), QUALITY)
        self.assertEqual(len(spec.fills), 2)
        self.assertEqual(len(spec.fills[0].loops), 2)
        # Side walls: 4 outer quads + 16 hole quads.
        self.assertEqual(len(spec.faces), 20)

    def test_hole_outside_rejected(self):
        with self.assertRaises(ModelingError) as ctx:
            Profile(curves.rect(1.0, 1.0), holes=(curves.circle(0.2, 8, center=(2.0, 0.0)),)).validate()
        self.assertEqual(ctx.exception.code, "profile.hole")

    def test_self_intersecting_ring_rejected(self):
        with self.assertRaises(ModelingError) as ctx:
            Profile(((0, 0), (1, 1), (1, 0), (0, 1))).validate()
        self.assertEqual(ctx.exception.code, "profile.outer")


class RevolveTests(unittest.TestCase):
    def test_sphere_volume(self):
        n = 64
        profile = tuple((math.sin(math.pi * i / n), -math.cos(math.pi * i / n)) for i in range(n + 1))
        shape = Revolve(profile=profile, segments=128)
        shape.validate("s")
        spec = generate(shape.to_recipe(), QUALITY)
        self.assertAlmostEqual(volume(spec), 4 / 3 * math.pi, delta=0.01)
        assert_outward(self, spec, (0, 0, 0))

    def test_cylinder_wall_with_caps_and_reversed_profile(self):
        for profile in (((1.0, 0.0), (1.0, 2.0)), ((1.0, 2.0), (1.0, 0.0))):
            spec = generate(Revolve(profile=profile, segments=128).to_recipe(), QUALITY)
            self.assertAlmostEqual(volume(spec), math.pi * 2, delta=0.01)
            assert_outward(self, spec, (0, 1, 0))

    def test_torus_closed_profile(self):
        ring = curves.circle(0.25, 32, center=(1.0, 0.0))
        spec = generate(Revolve(profile=ring + (ring[0],), segments=64).to_recipe(), QUALITY)
        self.assertAlmostEqual(volume(spec), 2 * math.pi ** 2 * 1.0 * 0.25 ** 2, delta=0.01)

    def test_partial_angle_is_open(self):
        spec = generate(Revolve(profile=((1.0, 0.0), (1.0, 1.0)), segments=8, angle=math.pi).to_recipe(), QUALITY)
        self.assertEqual(len(spec.faces), 8)

    def test_interior_zero_radius_rejected(self):
        with self.assertRaises(ModelingError):
            Revolve(profile=((0.0, 0.0), (0.0, 0.5), (1.0, 1.0))).validate("r")


class SweepTests(unittest.TestCase):
    def test_straight_sweep_matches_extrusion(self):
        shape = Sweep(profile=Profile(curves.circle(0.5, 64)), path=((0, 0, 0), (0, 1, 0), (0, 2, 0)))
        shape.validate("s")
        spec = generate(shape.to_recipe(), QUALITY)
        self.assertAlmostEqual(volume(spec), math.pi * 0.25 * 2, delta=0.01)
        assert_outward(self, spec, (0, 1, 0))

    def test_curved_path_keeps_volume(self):
        path = curves.bezier((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 2, 0), 48)
        spec = generate(Sweep(profile=Profile(curves.circle(0.1, 32)), path=path).to_recipe(), QUALITY)
        length = sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))
        self.assertAlmostEqual(volume(spec), math.pi * 0.01 * length, delta=0.002)

    def test_reversal_rejected(self):
        with self.assertRaises(ModelingError):
            Sweep(path=((0, 0, 0), (0, 1, 0), (0, 0, 0))).validate("s")


class LoftTests(unittest.TestCase):
    def test_two_circles_make_cylinder(self):
        ring = curves.circle(1.0, 128)
        shape = Loft(sections=(
            LoftSection(ring), LoftSection(ring, Transform(translation=(0, 2, 0)))))
        shape.validate("l")
        spec = generate(shape.to_recipe(), QUALITY)
        self.assertAlmostEqual(volume(spec), math.pi * 2, delta=0.01)
        assert_outward(self, spec, (0, 1, 0))

    def test_mismatched_counts_rejected(self):
        with self.assertRaises(ModelingError):
            Loft(sections=(LoftSection(curves.circle(1, 8)), LoftSection(curves.circle(1, 9)))).validate("l")


if __name__ == "__main__":
    unittest.main()
