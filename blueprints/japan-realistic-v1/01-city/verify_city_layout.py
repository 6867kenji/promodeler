"""Check exported GLB mesh bounds against the recorded future lots."""

import itertools
import json
import re
import struct
import sys
from pathlib import Path

output = Path(sys.argv[1]).resolve()
layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
with (output / "model.glb").open("rb") as stream:
    header = stream.read(20)
    if header[:4] != b"glTF" or header[16:20] != b"JSON":
        raise ValueError("Invalid GLB")
    gltf = json.loads(stream.read(struct.unpack_from("<I", header, 12)[0]))


def identity():
    return [[float(row == column) for column in range(4)] for row in range(4)]


def multiply(a, b):
    return [[sum(a[row][k] * b[k][column] for k in range(4))
             for column in range(4)] for row in range(4)]


def transform(node):
    if "matrix" in node:
        return [[node["matrix"][row + 4*column] for column in range(4)] for row in range(4)]
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    matrix = identity()
    rotations = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    scale, translation = node.get("scale", (1, 1, 1)), node.get("translation", (0, 0, 0))
    for row in range(3):
        for column in range(3):
            matrix[row][column] = rotations[row][column] * scale[column]
        matrix[row][3] = translation[row]
    return matrix


groups = {}
site_pattern = re.compile(r"^(site_b-\d+-\d+-\d+|infill_\d+_\d+_\d+_\d+|facility_warehouse|facility_subway_entry)_")
underground = {}


def visit(index, parent):
    node = gltf["nodes"][index]
    world = multiply(parent, transform(node))
    match = site_pattern.match(node.get("name", ""))
    if match and "mesh" in node:
        points = []
        for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
            accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
            corners = [(*corner, 1) for corner in itertools.product(*zip(accessor["min"], accessor["max"]))]
            points.extend([[sum(world[row][k] * corner[k] for k in range(4)) for row in range(3)]
                           for corner in corners])
        lo = [min(point[axis] for point in points) for axis in range(3)]
        hi = [max(point[axis] for point in points) for axis in range(3)]
        name = match[1]
        target = groups
        if name == "facility_subway_entry" and node.get("name", "").startswith((name+"_c_", name+"_p_")):
            target = underground
            if hi[1] >= 0 or lo[1] < -16:
                raise ValueError("Station underground component outside depth envelope")
        if name in target:
            old_lo, old_hi = target[name]
            lo, hi = [min(a, b) for a, b in zip(lo, old_lo)], [max(a, b) for a, b in zip(hi, old_hi)]
        target[name] = lo, hi
    for child in node.get("children", []):
        visit(child, world)


for root in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
    visit(root, identity())
if set(groups) != {record["id"] for record in layout["buildings"]+layout.get("facilities", [])}:
    raise ValueError("Exported building groups differ from the layout")
for name, (lo, hi) in groups.items():
    if min(lo[0], lo[2]) < -250 or max(hi[0], hi[2]) > 250 or hi[1] > 40:
        raise ValueError(f"Exported building outside city envelope: {name}")
    for reserve in layout["reservedSites"]:
        x0, z0, x1, z1 = reserve["bounds"]
        if lo[0] < x1 and hi[0] > x0 and lo[2] < z1 and hi[2] > z0:
            raise ValueError(f'Exported building {name} overlaps {reserve["id"]}')
for facility in layout.get("facilities", []):
    lo, hi = groups[facility["id"]]
    lot = next(r for r in layout["occupiedSites"] if r["id"] == facility["occupiedSite"])
    a, b, c, d = lot["bounds"]
    if not (a <= lo[0] <= hi[0] <= c and b <= lo[2] <= hi[2] <= d):
        raise ValueError("Exported facility is outside its dedicated site")
    for other, (other_lo, other_hi) in groups.items():
        if other != facility["id"] and lo[0] < other_hi[0] and hi[0] > other_lo[0] and lo[2] < other_hi[2] and hi[2] > other_lo[2]:
            raise ValueError(f"Exported facility overlaps {other}")
result = {"status": "ok", "exportedBuildings": layout["buildingCount"], "exportedStructures": len(groups), "exportedMeshBoundsChecked": True,
          "undergroundBounds": {name: {"min":lo,"max":hi} for name,(lo,hi) in underground.items()},
          "reservedSitesClear": True, "reservedSites": layout["reservedSites"],
          "baseBuildingsPerBlock": 20, "facilities": layout.get("facilities", []),
          "facilityFitsDedicatedSite": True, "frontageSetbackM": layout["frontageSetbackM"],
          "sideGapRangeM": [min(g["distance_m"] for g in layout["sideGaps"]),
                            max(g["distance_m"] for g in layout["sideGaps"])],
          "buildingBounds": {name: {"min": lo, "max": hi} for name, (lo, hi) in groups.items()}}
(output / "layout-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("CITY_LAYOUT_VALIDATED", len(groups), "structures, dedicated sites checked")
