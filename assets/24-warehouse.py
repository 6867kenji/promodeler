"""Standalone warehouse; the same shell is placed in the Shiomi district."""

import math
from promodeler.core import Asset, AssetGenerator, Camera, RenderSettings
from assets.warehouse import materials, tile_specs, warehouse_parts


def build(_):
    return Asset(name="Warehouse", materials=materials(), parts=tuple(warehouse_parts()),
                 extras={"tiled_materials": tile_specs(), "reference": "warehouse / WSE_11: visual reference",
                         "loadingBayClearanceM": [4.45, 4.6], "openLoadingBay": "warehouse_bay_1"})


asset = AssetGenerator(name="Warehouse", parameters={}, build=build, seed=24)
blueprint = "../blueprints/japan-realistic-v1/24-warehouse/blueprint.json"
blueprint_part_map = {"foundation": ("warehouse_foundation",),
                      "roof": tuple(p.id for p in warehouse_parts() if "_roof_" in p.id),
                      "skylights": tuple(p.id for p in warehouse_parts() if "_skylight_" in p.id),
                      "open-bay": ("warehouse_bay_1_hood", "warehouse_bay_1_jamb_0", "warehouse_bay_1_jamb_1"),
                      "personnel-door": ("warehouse_personnel_door",)}
blueprint_required_parts = ("warehouse_ridge_cap", "warehouse_front_gable", "warehouse_rear_gable",
                            "warehouse_personnel_handle", "warehouse_truss_tie_2")
blueprint_texel_parts = ()
render = RenderSettings(resolution=960, aspect_ratio=1.6, views=(), passes=("shaded",),
                        samples=32, environment="sunny", cameras=(
                            Camera("warehouse_oblique", position=(34, 26, 38), target=(0, 3, 0), fov=math.radians(55)),
                            Camera("loading_front", position=(0, 9, 43), target=(0, 3.3, 10), fov=math.radians(54)),
                            Camera("roof_detail", position=(18, 17, 12), target=(6, 7.1, 1), fov=math.radians(55)),
                            Camera("loading_bay", position=(3.8, 2.3, 18), target=(0, 2.1, 10), fov=math.radians(70)),
                            Camera("wall_detail", position=(16, 2.7, 16), target=(11.6, 1.7, 10.3), fov=math.radians(60)),
                        ))
