"""Assemble the three station designs in their documented common coordinates."""

import json
from dataclasses import replace
from pathlib import Path
from promodeler.core import Asset, ModelingError
from assets.blueprint_models import load_design
from assets.blueprint_spaces import build_space


ROOT = Path(__file__).resolve().parents[1]/"blueprints/japan-realistic-v1"
ASSEMBLY = json.loads((ROOT/"subway-assembly.json").read_text(encoding="utf-8"))
PREFIXES = {"subway-entrance":"e", "subway-concourse":"c", "subway-platform":"p"}


def connections(origin=(0.,0.,0.)):
    ports = {}
    for item in ASSEMBLY["assets"]:
        design = load_design(item["folder"])
        delta = item["translation_m"]
        if any(item["rotation_rad"]):
            raise ModelingError("station.rotation", "Station components currently share unrotated axes")
        for port in design["ports"]:
            ports[item["id"]+":"+port["id"]] = {**port,
                "floor_center_world_m": [a+b+c for a,b,c in zip(port["floor_center_local_m"],delta,origin)]}
    result = []
    for first,second in ASSEMBLY["connections"]:
        a,b = ports[first],ports[second]
        if any(abs(x-y) > 1e-7 for x,y in zip(a["floor_center_world_m"],b["floor_center_world_m"])):
            raise ModelingError("station.portPosition", first)
        if any(abs(x+y) > 1e-7 for x,y in zip(a["outward_normal_xyz"],b["outward_normal_xyz"])):
            raise ModelingError("station.portNormal", first)
        result.append({"from":first,"to":second,"floor_center_world_m":a["floor_center_world_m"],
                       "clear_width_m":min(a["clear_width_m"],b["clear_width_m"]),
                       "clear_height_m":min(a["clear_height_m"],b["clear_height_m"])})
    return result


def station(prefix="station", origin=(0.,0.,0.)):
    parts, materials, tiled = [],[],{}
    for item in ASSEMBLY["assets"]:
        group = PREFIXES[item["id"]]
        source = build_space(load_design(item["folder"]),item["folder"])
        delta = tuple(a+b for a,b in zip(origin,item["translation_m"]))
        material_map = {m.id:f"st_{group}_"+m.id for m in source.materials}
        materials.extend(replace(m,id=material_map[m.id]) for m in source.materials)
        tiled.update({material_map[k]:v for k,v in source.extras.get("tiled_materials",{}).items()})
        for part in source.parts:
            # The standalone assets retain their rigs; this assembled layout
            # is a fixed open station for checking continuous pedestrian access.
            if group == "e" and part.id == "closure_shutter":
                continue
            transform = part.transform
            if group == "c" and part.id in ("gate_flap_7","gate_flap_edge_7"):
                transform = replace(transform,translation=(3.59,transform.translation[1],transform.translation[2]),
                                    rotation=(0,1.5707963267948966,0))
            parts.append(replace(part,id=f"{prefix}_{group}_"+part.id,material=material_map[part.material],
                                 parent_joint=None,transform=replace(transform,
                                     translation=tuple(a+b for a,b in zip(transform.translation,delta)))))
    return Asset(name="SubwayStation",materials=tuple(materials),parts=tuple(parts),
                 extras={"tiled_materials":tiled,"stationConnections":connections(origin),
                         "stationOrigin":origin,"mode":"fixed_open_layout","wideGateClearanceM":.9,
                         "reference":"SubwayPassage: visual reference; locally generated geometry and textures"})
