import os
import tempfile
import unittest

import numpy as np

from promodeler.core import Asset, Material, MeshFile, ModelingError, Part, build_recipe, dump_recipe


def write_tetra(path: str, with_weights: bool = True) -> None:
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int32)
    data = {"vertices": vertices, "faces": faces}
    if with_weights:
        data["weights"] = np.eye(4, 2, dtype=np.float32)
        data["group_names"] = np.array(["a", "b"])
    np.savez(path, **data)


class MeshFileTests(unittest.TestCase):
    def test_recipe_carries_hash_and_changes_with_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.npz")
            write_tetra(path)
            shape = MeshFile(path)
            shape.validate("s")
            recipe = shape.to_recipe()
            self.assertEqual(recipe["kind"], "mesh_file")
            self.assertEqual(len(recipe["sha256"]), 64)
            asset = Asset("x", (Material("m"),), (Part("body", shape, "m", skinned=False),))
            first = dump_recipe(build_recipe(asset))
            write_tetra(path, with_weights=False)
            second = dump_recipe(build_recipe(asset))
            self.assertNotEqual(first, second)

    def test_missing_or_wrong_file(self):
        with self.assertRaises(ModelingError):
            MeshFile("C:/nope/missing.npz").validate("s")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.obj")
            open(path, "w").write("o x\n")
            with self.assertRaises(ModelingError) as ctx:
                MeshFile(path).validate("s")
            self.assertEqual(ctx.exception.code, "meshfile.format")


if __name__ == "__main__":
    unittest.main()
