"""Garment fitting between body profiles: mesh IO, profiles from a mesh, offsets preserved across bodies."""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from promodeler.character import fit

ROOT = Path(__file__).resolve().parent.parent
FEMALE = ROOT / "character" / "profiles" / "human_female.json"
MALE = ROOT / "character" / "profiles" / "human_male.json"


def cylinder(centre, axis_from, axis_to, radius, rings=12, segments=16):
    """A closed tube from axis_from to axis_to (both (x, y, z)) with the given radius: vertices and triangle faces."""
    a = np.array(axis_from, dtype=float)
    b = np.array(axis_to, dtype=float)
    d = b - a
    d /= np.linalg.norm(d)
    helper = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(helper, d); e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    verts, faces = [], []
    for i in range(rings + 1):
        c = a + (b - a) * i / rings
        for j in range(segments):
            t = 2 * math.pi * j / segments
            verts.append(c + radius * (math.cos(t) * e1 + math.sin(t) * e2))
    for i in range(rings):
        for j in range(segments):
            p0 = i * segments + j; p1 = i * segments + (j + 1) % segments
            p2 = (i + 1) * segments + j; p3 = (i + 1) * segments + (j + 1) % segments
            faces += [[p0, p1, p3], [p0, p3, p2]]
    return np.array(verts), np.array(faces)


def mannequin(torso_radius=0.15, arm_radius=0.05, leg_radius=0.09):
    """Torso tube (y 0.9..1.5), arms from the shoulders down-out, legs from the hips down."""
    parts = [cylinder(None, (0, 0.85, 0), (0, 1.55, 0), torso_radius)]
    landmarks = {"Hips": [0, 0.95, 0], "Neck": [0, 1.5, 0], "Head": [0, 1.6, 0]}
    for sign, side in ((-1, "Left"), (1, "Right")):
        sh = (sign * 0.17, 1.45, 0); hand = (sign * 0.55, 1.05, 0)
        parts.append(cylinder(None, sh, hand, arm_radius))
        landmarks[side + "Arm"] = list(sh); landmarks[side + "Hand"] = list(hand)
        hip = (sign * 0.09, 0.92, 0); foot = (sign * 0.1, 0.05, 0)
        parts.append(cylinder(None, hip, foot, leg_radius))
        landmarks[side + "UpLeg"] = list(hip); landmarks[side + "Foot"] = list(foot)
    verts, faces, base = [], [], 0
    for v, f in parts:
        verts.append(v); faces.append(f + base); base += len(v)
    return fit.Mesh(vertices=np.vstack(verts), faces=np.vstack(faces)), landmarks


class MeshIoTests(unittest.TestCase):
    def test_glb_roundtrip_and_obj(self):
        mesh, _ = mannequin()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.glb"
            fit.write_glb(path, mesh)
            back = fit.read_glb(path)
            self.assertEqual(back.vertices.shape, mesh.vertices.shape)
            self.assertEqual(back.faces.shape, mesh.faces.shape)
            self.assertTrue(np.allclose(back.vertices, mesh.vertices, atol=1e-6))
            self.assertIsNotNone(back.normals)
            obj = Path(tmp) / "m.obj"
            obj.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n", encoding="utf-8")
            quad = fit.read_obj(obj)
            self.assertEqual(quad.faces.tolist(), [[0, 1, 2], [0, 2, 3]])


class ProfileFromMeshTests(unittest.TestCase):
    def test_radii_match_the_mannequin(self):
        mesh, landmarks = mannequin()
        profile = fit.profile_from_mesh(mesh, landmarks, race="test")
        self.assertEqual(profile["schema"], fit.PROFILE_SCHEMA)
        torso = [s for s in profile["torso_slices"] if 1.0 < s["y"] < 1.2]
        self.assertTrue(torso)
        for s in torso:
            radii = [math.hypot(a, b) for a, b in s["points"]]
            self.assertAlmostEqual(max(radii), 0.15, delta=0.006)
        arm = profile["arms"]["left"]
        self.assertGreater(len(arm["slices"]), 5)
        mid = arm["slices"][len(arm["slices"]) // 2]
        radii = [math.hypot(a, b) for a, b in mid["points"]]
        self.assertAlmostEqual(max(radii), 0.05, delta=0.012)   # sections cut obliquely through a tube read a little wide
        leg = profile["legs"]["right"]
        self.assertGreater(len(leg["slices"]), 10)
        body = fit.BodyProfile(profile)
        self.assertIn("left", body.arms)
        self.assertIn("right", body.legs)


class FitTests(unittest.TestCase):
    def test_identity_fit_keeps_the_garment_and_offsets_survive_a_body_change(self):
        mesh, landmarks = mannequin()
        source = fit.BodyProfile(fit.profile_from_mesh(mesh, landmarks))
        fat_mesh, _ = mannequin(torso_radius=0.20, arm_radius=0.06, leg_radius=0.11)
        target = fit.BodyProfile(fit.profile_from_mesh(fat_mesh, landmarks))
        # A "garment": the torso tube with 3 cm of ease around the waist band.
        garment, _ = cylinder(None, (0, 1.0, 0), (0, 1.3, 0), 0.18), None
        garment_mesh = fit.Mesh(vertices=garment[0], faces=garment[1])
        same = fit.fit_mesh(garment_mesh, source, source)
        self.assertLess(np.abs(same.vertices - garment_mesh.vertices).max(), 0.004)
        fitted = fit.fit_mesh(garment_mesh, source, target)
        radii = np.hypot(fitted.vertices[:, 0], fitted.vertices[:, 2])
        self.assertAlmostEqual(float(np.median(radii)), 0.23, delta=0.012)   # 0.20 body + the 0.03 ease
        torso_only = np.array([not fit.segment_weights(source, p) for p in garment_mesh.vertices])
        self.assertGreater(torso_only.sum(), len(torso_only) // 2)
        self.assertTrue(np.allclose(fitted.vertices[torso_only, 1], garment_mesh.vertices[torso_only, 1], atol=1e-6))   # same skeleton: heights keep

    def test_race_profiles_fit_end_to_end(self):
        source = fit.BodyProfile.load(FEMALE)
        target = fit.BodyProfile.load(MALE)
        p = np.array([0.0, 1.3, 0.16])   # a point 2-3 cm in front of the chest
        q = fit.fit_point(p, source, target)
        self.assertLess(abs(q[1] - p[1]), 1e-4)
        self.assertLess(np.linalg.norm(q - p), 0.08)
        sleeve = np.array([-0.35, 1.45, 0.03])   # on the left upper arm
        weights = fit.segment_weights(source, sleeve)
        self.assertIn("arm_left", weights)
        self.assertGreater(weights["arm_left"], 0.9)


if __name__ == "__main__":
    unittest.main()
