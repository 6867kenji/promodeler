"""Blender: -- BUILD_DIR. Re-import and preserve an editable, packed Blend."""

import hashlib
import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


output = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
source = output / "model.glb"
data = source.read_bytes()
if data[:4] != b"glTF" or int.from_bytes(data[8:12], "little") != len(data):
    raise ValueError("Invalid GLB header")
document = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")])
if any("uri" in image for image in document.get("images", [])):
    raise ValueError("City GLB has an external image")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
missing = [image.name for image in bpy.data.images if image.source == "FILE"
           and not image.packed_file and not Path(bpy.path.abspath(image.filepath)).is_file()]
if missing:
    raise ValueError(f"Missing images: {missing}")
layout = json.loads((output / "recipe.json").read_text(encoding="utf-8"))["asset"]["extras"]["city_layout"]
roof_sites = {obj.name.split("_roof_ac_", 1)[0] for obj in meshes if "_roof_ac_" in obj.name}
expected_sites = {site["id"] for site in layout["buildings"]}
if roof_sites != expected_sites:
    raise ValueError(f"Roof equipment sites differ: {len(roof_sites)} / {len(expected_sites)}")
for reserve in layout["reservedSites"]:
    if "reserved_" + reserve["id"] not in {obj.name for obj in meshes}:
        raise ValueError(f"Missing reserved site: {reserve['id']}")
textures = {mat.name: [node.image.name for node in mat.node_tree.nodes if node.type == "TEX_IMAGE" and node.image]
            for mat in bpy.data.materials if mat.use_nodes}
station_checks = []
for prefix in ("tile", "brick_red", "brick_walk", "site_paving", "roof_membrane", "asphalt"):
    if not any(name.startswith(prefix + "_tiled") and len(images) >= 3 for name, images in textures.items()):
        raise ValueError(f"Missing PBR maps for {prefix}")
for facility in layout.get("facilities", []):
    prefix = facility["id"]
    if facility.get("kind") == "subway":
        for suffix in ("_e_station-sign", "_c_floor", "_p_island-floor"):
            if prefix + suffix not in {obj.name for obj in meshes}:
                raise ValueError("Missing connected station component: " + suffix)
        for material in ("st_e_wall-tile", "st_c_floor-tile", "st_p_floor-tile"):
            if not any(name.startswith(material+"_tiled") and len(images) >= 3 for name, images in textures.items()):
                raise ValueError("Missing subway PBR maps: " + material)
        from mathutils.bvhtree import BVHTree
        for name in ("ground", "block_1_1"):
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise ValueError("Missing opened ground slab: " + name)
            points = [obj.matrix_world @ v.co for v in obj.data.vertices]
            tree = BVHTree.FromPolygons(points, [tuple(p.vertices) for p in obj.data.polygons])
            if tree.ray_cast(Vector((-28.1, 54, .25)), Vector((0,0,-1)), .7)[0] is not None:
                raise ValueError("Ground slab blocks the station stairwell")
            if tree.ray_cast(Vector((-28.1,48,.25)),Vector((0,0,-1)),.7)[0] is None:
                raise ValueError("Uncovered ground behind the station canopy")
        surfaces = [o for o in meshes if o.name.startswith(("walk_ns_", "lot_subway_walk_")) or
                    o.name in (prefix+"_e_street_landing", prefix+"_e_entry-stair_landing_0")]
        vertices, faces = [], []
        for obj in surfaces:
            start = len(vertices)
            vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
            faces.extend(tuple(start+i for i in polygon.vertices) for polygon in obj.data.polygons)
        walk_tree = BVHTree.FromPolygons(vertices, faces)
        points = [(x,-61.9) for x in (-8,-10,-12,-14,-16,-18,-20,-22,-24,-26,-28.1)] + [(-28.1,z) for z in (-61.3,-60.5,-59.5,-58.5)]
        for x,z in points:
            hit = walk_tree.ray_cast(Vector((x,-z,.25)),Vector((0,0,-1)),.3)[0]
            if hit is None or abs(hit.z-.15) > .015:
                raise ValueError(f"Sidewalk-to-stair floor discontinuity at {x,z}: {hit}")
        entry_objects = [o for o in meshes if o.name.startswith(prefix+"_e_") or o.name in ("ground","block_1_1")]
        vertices, faces = [], []
        for obj in entry_objects:
            start = len(vertices)
            vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
            faces.extend(tuple(start+i for i in polygon.vertices) for polygon in obj.data.polygons)
        entry_tree = BVHTree.FromPolygons(vertices,faces)
        design = json.loads((Path(__file__).resolve().parents[1]/"17-subway-entrance/blueprint.json").read_text(encoding="utf-8"))
        for tread in design["stairs"][0]["treads"]:
            x = sum(tread["x_range_m"])/2+facility["position_m"][0]
            y = tread["top_y_m"]+facility["position_m"][1]
            z = sum(tread["z_range_m"])/2+facility["position_m"][2]
            if entry_tree.ray_cast(Vector((x,-z,y+.045)),Vector((0,0,1)),1.805)[0] is not None:
                raise ValueError("Ground closure blocks stair headroom: "+tread["id"])
        station_checks.append({"facility":prefix,"groundOpening":True,"groundClosedBehindCanopy":True,"sidewalkFloorSamples":len(points),
                               "entranceStairHeadroomSamples":36,"headroomM":1.85,
                               "streetY":facility["stationOrigin_m"][1],"concourseY":facility["stationOrigin_m"][1]-6,
                               "platformY":facility["stationOrigin_m"][1]-12})
        continue
    if prefix + "_foundation" not in {obj.name for obj in meshes}:
        raise ValueError("Missing warehouse facility")
    panes = [obj for obj in meshes if re.fullmatch(re.escape(prefix)+r"_skylight_-?\d+_\d+", obj.name)]
    if len(panes) != 12:
        raise ValueError(f"Expected 12 warehouse skylights, got {len(panes)}")
    for material in ("wh_roof", "wh_wall", "wh_brick", "wh_shutter"):
        if not any(name.startswith(material+"_tiled") and len(images) >= 3 for name, images in textures.items()):
            raise ValueError(f"Missing warehouse PBR maps: {material}")
blend = output / "model.blend"
# Leave the editable file with an overview camera and usable sunlight.
camera_data = bpy.data.cameras.new("CityOverview")
camera = bpy.data.objects.new("CityOverview", camera_data)
bpy.context.scene.collection.objects.link(camera)
camera.location = (440, -440, 440)
camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.clip_end = 2500
camera.data.lens = 40
bpy.context.scene.camera = camera
sun_data = bpy.data.lights.new("CitySun", "SUN")
sun_data.energy = 3
sun = bpy.data.objects.new("CitySun", sun_data)
bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (.6, -.3, -.5)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_location = (0, 0, 10)
            area.spaces.active.region_3d.view_distance = 600
            area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
bpy.ops.file.pack_all()
bpy.context.preferences.filepaths.save_version = 0
bpy.context.scene.unit_settings.system = "METRIC"
bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
result = {"status": "ok", "glb": str(source), "sha256": hashlib.sha256(data).hexdigest(),
          "meshes": len(meshes), "roofEquipmentBuildings": len(roof_sites),
          "reservedSites": layout["reservedSites"], "buildingCount": layout["buildingCount"],
          "images": len(bpy.data.images), "embeddedImages": True, "blenderReimport": True,
          "blend": str(blend), "blendBytes": blend.stat().st_size,
          "facilities": layout.get("facilities", []),
          "stationGroundOpeningChecked": bool(station_checks), "stationChecks":station_checks,
          "reference": "nyc-set-8 / warehouse / SubwayPassage: visual references; newly generated geometry and PBR maps"}
(output / "import-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("CITY_IMPORT_VALIDATED", len(meshes), "meshes", len(bpy.data.images), "images", flush=True)
