import unittest

from promodeler.core import (
    Asset, Box, Clip, ExportSettings, Fur, Joint, JointTransform, Keyframe, LOD, Material, ModelingError, Part, Pose,
    RenderSettings, Rig, Scatter, Sphere, build_recipe, Curvature, Noise,
)


def rig2() -> Rig:
    return Rig("r", joints=(Joint("a", (0, 0, 0), (0, 1, 0)), Joint("b", (0, 1, 0), (0, 2, 0), parent="a")))


class RigTests(unittest.TestCase):
    def test_valid_rig_asset(self):
        m = Material("m")
        pose = Pose("bend", {"b": JointTransform(rotation=(0.3, 0, 0))})
        clip = Clip("c", 2.0, (Keyframe(0.0, None), Keyframe(1.0, "bend"), Keyframe(2.0, None)))
        asset = Asset("x", (m,), (Part("body", Box(), "m", skinned=True), Part("cap", Box(), "m", parent_joint="b")),
                      rig=rig2(), poses=(pose,), clips=(clip,))
        asset.validate()
        recipe = build_recipe(asset, render=RenderSettings(pose="bend"), export=ExportSettings(formats=("glb", "usdz")))
        self.assertEqual(recipe["asset"]["rig"]["joints"][1]["parent"], "a")
        self.assertEqual(recipe["asset"]["clips"][0]["keyframes"][1]["pose"], "bend")
        self.assertEqual(recipe["export"]["formats"], ["glb", "usdz"])

    def test_rig_errors(self):
        with self.assertRaises(ModelingError):
            Rig("r", joints=(Joint("a", (0, 0, 0), (0, 0, 0)),)).validate()
        with self.assertRaises(ModelingError) as ctx:
            Rig("r", joints=(Joint("a", (0, 0, 0), (0, 1, 0), parent="a"),)).validate()
        self.assertEqual(ctx.exception.code, "joint.parentCycle")
        m = Material("m")
        with self.assertRaises(ModelingError) as ctx:
            Asset("x", (m,), (Part("body", Box(), "m", skinned=True),)).validate()
        self.assertEqual(ctx.exception.code, "part.binding")
        with self.assertRaises(ModelingError):
            Asset("x", (m,), (Part("body", Box(), "m"),), rig=rig2(),
                  poses=(Pose("p", {"zzz": JointTransform()}),)).validate()
        with self.assertRaises(ModelingError):
            Asset("x", (m,), (Part("body", Box(), "m"),), rig=rig2(), poses=(Pose("p", {"a": JointTransform()}),),
                  clips=(Clip("c", 1.0, (Keyframe(0.0, "p"), Keyframe(0.5, "missing")),),)).validate()
        with self.assertRaises(ModelingError) as ctx:
            build_recipe(Asset("x", (m,), (Part("body", Box(), "m"),)), render=RenderSettings(pose="nope"))
        self.assertEqual(ctx.exception.code, "render.pose")

    def test_pose_space(self):
        JointTransform(rotation=(0.1, 0, 0), space="world").validate("t")
        with self.assertRaises(ModelingError):
            JointTransform(space="camera").validate("t")
        self.assertEqual(JointTransform(space="world").to_recipe()["space"], "world")

    def test_export_settings(self):
        with self.assertRaises(ModelingError):
            ExportSettings(formats=("usdz",)).validate()
        with self.assertRaises(ModelingError):
            ExportSettings(formats=("glb", "fbx")).validate()


class GeneratedTests(unittest.TestCase):
    def test_scatter_and_fur_reference_regular_parts(self):
        m = Material("m")
        rock = Part("rock", Sphere(), "m", lods=(LOD(5.0, 0.5), LOD(10.0, 0.2)))
        moss = Part("moss", Scatter(surface="rock", instance=Sphere(0.01), density=50), "m")
        fur = Part("fur", Fur(surface="rock", density=100), "m")
        Asset("x", (m,), (rock, moss, fur)).validate()
        with self.assertRaises(ModelingError) as ctx:
            Asset("x", (m,), (rock, Part("bad", Scatter(surface="moss", instance=Sphere(0.01)), "m"), moss)).validate()
        self.assertEqual(ctx.exception.code, "scatter.surface")
        with self.assertRaises(ModelingError):
            Scatter(surface="rock", instance=Sphere(0.01), mask=Curvature()).validate("s")
        Scatter(surface="rock", instance=Sphere(0.01), mask=Noise().smoothstep(0.3, 0.6)).validate("s")
        with self.assertRaises(ModelingError):
            Fur(surface="rock", sides=2).validate("f")
        with self.assertRaises(ModelingError):
            Part("rock", Sphere(), "m", lods=(LOD(10.0, 0.5), LOD(5.0, 0.2))).validate()
        with self.assertRaises(ModelingError):
            Part("moss", Scatter(surface="rock", instance=Sphere(0.01)), "m", lods=(LOD(5.0, 0.5),)).validate()


if __name__ == "__main__":
    unittest.main()
