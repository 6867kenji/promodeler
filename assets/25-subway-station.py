"""One connected GLB from the ground entrance through B1 to the B2 platform."""

import math
from promodeler.core import AssetGenerator, Camera, Light, RenderSettings
from assets.subway_station import station

asset = AssetGenerator(name="SubwayStation",parameters={},build=lambda _:station(),seed=25)
blueprint = "../blueprints/japan-realistic-v1/25-subway-station/blueprint.json"
blueprint_dependencies = tuple("../blueprints/japan-realistic-v1/"+folder+"/blueprint.json" for folder in
                               ("17-subway-entrance","18-subway-concourse","19-subway-platform")) + ("../blueprints/japan-realistic-v1/subway-assembly.json",)
blueprint_part_map = {"entrance":("station_e_station-sign",),"concourse":("station_c_floor",),"platform":("station_p_island-floor",)}
blueprint_required_parts = ("station_e_entry-stair_landing_2","station_c_bank_A_bottom_link","station_p_ceiling")
blueprint_envelope_mode = "maximum"
blueprint_texel_parts = ()
source = station()
cutaway = tuple(p.id for p in source.parts if p.id in ("station_c_ceiling","station_p_ceiling","station_c_side_wall_1","station_p_side_wall_10.4","station_e_canopy-frame") or
                 p.id.startswith(("station_e_entry_wall_e_","station_e_entry_soffit_","station_e_lower_hall_ceiling","station_e_canopy_edge_")))
lights = tuple(Light(f"b1_{z}",position=(0,-3.2,z),energy=200,size=5) for z in range(-42,43,12)) + tuple(
    Light(f"b2_{z}",position=(0,-8.55,z),energy=180,size=5) for z in range(-60,61,12)) + tuple(
    Light(f"entry_{i}",position=(0,-.8-i*1.35,-69+i*2.8),energy=140,size=2.5) for i in range(4))
render = RenderSettings(resolution=960,aspect_ratio=1.6,views=(),passes=("shaded",),samples=24,background=(.16,.16,.16),environment="overcast",lights=lights,cameras=(
    Camera("station_section",position=(85,40,100),target=(0,-6,-8),fov=math.radians(63),hide_parts=cutaway),
    Camera("entrance_to_b1",position=(-2.1,1.65,-74.5),target=(-2.1,-3.3,-62),fov=math.radians(68)),
    Camera("b1_connection",position=(0,-4.35,-52),target=(0,-4.8,-38),fov=math.radians(66)),
    Camera("ticket_hall",position=(5.2,-4.2,-43.8),target=(8.8,-5.0,-38.5),fov=math.radians(65)),
    Camera("vending_close",position=(6.0,-4.8,-45.15),target=(8.85,-5.05,-45.15),fov=math.radians(58)),
    Camera("gate_oblique",position=(5.8,-4.25,-34),target=(-1.2,-5.2,-28),fov=math.radians(67)),
    Camera("gates_open",position=(3.08,-4.35,-33),target=(3.08,-5.3,-25),fov=math.radians(68)),
    Camera("b1_to_b2",position=(-1.9,-4.35,-17.5),target=(-1.9,-9.,-7),fov=math.radians(65)),
    Camera("platform_arrival",position=(-1.9,-10.35,-.8),target=(0,-10.6,10),fov=math.radians(68)),
))
