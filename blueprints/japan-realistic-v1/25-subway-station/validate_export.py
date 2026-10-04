"""Blender: -- BUILD_DIR [DESIGN_FOLDER]. Import GLB, pack Blend, audit access."""
import hashlib
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

output = Path(sys.argv[sys.argv.index('--')+1]).resolve()
folder = sys.argv[sys.argv.index('--')+2] if len(sys.argv) > sys.argv.index('--')+2 else '25-subway-station'
source = output/'model.glb'
data = source.read_bytes()
assert data[:4] == b'glTF' and int.from_bytes(data[8:12],'little') == len(data)
doc = json.loads(data[20:20+int.from_bytes(data[12:16],'little')])
assert all('uri' not in im for im in doc.get('images',[])), 'External GLB images'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
assert meshes
assert all(im.packed_file or im.source != 'FILE' or Path(bpy.path.abspath(im.filepath)).is_file() for im in bpy.data.images)

def tree(objects):
    vertices, faces = [],[]
    for o in objects:
        start = len(vertices)
        vertices.extend(Vector((v.x,v.z,-v.y)) for v in (o.matrix_world @ v.co for v in o.data.vertices))
        faces.extend(tuple(start+i for i in p.vertices) for p in o.data.polygons)
    return BVHTree.FromPolygons(vertices, faces)

route_result = None
if folder == '25-subway-station':
    all_tree = tree(meshes)
    floor_tree = tree([o for o in meshes if o.name in ('station_c_floor','station_p_island-floor','station_e_lower-floor') or
        any(s in o.name for s in ('-tread-', '_landing_', '_bottom_link', 'entry_bottom_landing'))])
    root = Path(__file__).resolve().parents[1]
    entry = json.loads((root/'17-subway-entrance/blueprint.json').read_text(encoding='utf-8'))
    concourse = json.loads((root/'18-subway-concourse/blueprint.json').read_text(encoding='utf-8'))
    route = []
    def point(x,y,z,tag): route.append((x,y,z,tag))
    def stair(design, index, delta, x):
        s = design['stairs'][index]
        for t in s['treads']:
            point(x,t['top_y_m']+delta[1],sum(t['z_range_m'])/2+delta[2],t['id'])
        profile = s['section_profile_zy']
        for i,(a,b) in enumerate(zip(profile,profile[1:])):
            if abs(a[1]-b[1]) < 1e-6:
                point(x,a[1]+delta[1],(a[0]+b[0])/2+delta[2],s['id']+f' landing {i}')
    stair(entry,0,(0,0,-62),-2.1)
    for z in range(-59,-30): point(-2.1,-6,z,'entry to B1')
    for x in (-1,0,1,2,3.08): point(x,-6,-31,'approach wide gate')
    for z in (-30,-29,-28.5,-28,-27.5,-27,-26,-25,-24,-23,-22,-21): point(3.08,-6,z,'wide gate')
    for x in (2,1,0,-1,-1.9): point(x,-6,-21,'paid concourse')
    for z in (-20,-19): point(-1.9,-6,z,'approach stairs A')
    stair(concourse,0,(0,-6,0),-1.9)
    stair(concourse,1,(0,-6,0),-1.9)
    point(-1.9,-12,21,'bank B arrival')
    for z in (-1,0,1,2): point(-1.9,-12,z,'platform arrival')
    for x in (-2.5,-3.2): point(x,-12,2,'platform lateral walkway')
    for z in (3,4,6,8,10,12,14,16,18): point(-3.2,-12,z,'platform clear walkway')
    problems = []
    for x,y,z,tag in route:
        foot = Vector((x,y+.10,z))
        hit = floor_tree.ray_cast(foot,Vector((0,-1,0)),.5)[0]
        if hit is None or abs(hit.y-y) > .025:
            problems.append({'point':[x,y,z],'tag':tag,'reason':'missing or discontinuous floor','hit':list(hit) if hit else None})
        head = all_tree.ray_cast(Vector((x,y+.045,z)),Vector((0,1,0)),1.805)[0]
        if head is not None:
            problems.append({'point':[x,y,z],'tag':tag,'reason':'headroom below 1.85m','hit':list(head)})
    for height in (.45,.75,1.05,1.65):
        hit = all_tree.ray_cast(Vector((3.08,-6+height,-30)),Vector((0,0,1)),5)[0]
        if hit is not None:
            problems.append({'tag':'wide gate horizontal crossing','height':height,'hit':list(hit)})
    route_result = {'status':'ok' if not problems else 'failed','sampleCount':len(route),'headroomM':1.85,
                    'wideGateM':.9,'problems':problems,'scope':'GLB geometry rays, fixed open gate; runtime collision and lift animation excluded'}
    (output/'access-validation.json').write_text(json.dumps(route_result,ensure_ascii=False,indent=2),encoding='utf-8')
    if problems: raise ValueError(f'Access validation failed: {problems[:4]}')

camera_data = bpy.data.cameras.new('ReviewCamera')
camera = bpy.data.objects.new('ReviewCamera',camera_data)
bpy.context.scene.collection.objects.link(camera)
pos,target = ((85,-100,40),(0,8,-6)) if folder == '25-subway-station' else ((45,-100,50),(0,0,-2)) if folder == '18-subway-concourse' else ((45,-135,55),(0,0,0)) if folder == '19-subway-platform' else ((24,-32,22),(0,0,0))
camera.location = pos
camera.rotation_euler = (Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.clip_end = 1000
bpy.context.scene.camera = camera
camera.data.lens = 40
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            region = area.spaces.active.region_3d
            region.view_location = target
            region.view_distance = 150 if folder != '17-subway-entrance' else 45
            region.view_rotation = camera.rotation_euler.to_quaternion()
sun_data = bpy.data.lights.new('ReviewSun','SUN'); sun_data.energy = 2
sun = bpy.data.objects.new('ReviewSun',sun_data); bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (.6,-.3,-.5)
if folder == '25-subway-station':
    for level,energy in ((-3.2,200),(-8.55,180)):
        for z in range(-42,43,12):
            ld = bpy.data.lights.new(f'Interior_{level}_{z}','AREA'); ld.energy=energy; ld.shape='DISK'; ld.size=5
            lo = bpy.data.objects.new(ld.name,ld); bpy.context.scene.collection.objects.link(lo); lo.location=(0,-z,level)
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.file.pack_all()
blend = output/'model.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend),compress=True)
result = {'status':'ok','glb':str(source),'sha256':hashlib.sha256(data).hexdigest(),'meshes':len(meshes),
          'images':len(doc.get('images',[])),'embeddedImages':True,'blenderReimport':True,'blend':str(blend),
          'blendBytes':blend.stat().st_size,'access':route_result,'armatures':sum(o.type=='ARMATURE' for o in bpy.context.scene.objects)}
(output/'import-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUBWAY_IMPORT_VALIDATED',len(meshes),'meshes',flush=True)
